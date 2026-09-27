#!/usr/bin/env python3
"""Build and flash ZMK targets discovered from Compose and build.yaml."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CONTAINER_WORKSPACE = "/workspaces/zmk"
CONTAINER_CONFIG = "/workspaces/zmk-config"
CONTAINER_MODULES = "/workspaces/zmk-modules"
USB_MARKERS = ("INFO_UF2.TXT", "CURRENT.UF2")
TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UserError(Exception):
    """An expected error that should be shown without a traceback."""


@dataclass(frozen=True)
class ComposeInfo:
    path: Path
    service: str
    workspace_host: Path
    config_host: Path
    modules_host: Path | None
    extra_modules: tuple[str, ...]


@dataclass(frozen=True)
class BuildTarget:
    artifact_name: str
    board: str
    shield: str
    snippets: tuple[str, ...]
    cmake_args: tuple[str, ...]


@dataclass(frozen=True)
class TargetContext:
    compose: ComposeInfo
    target: BuildTarget
    build_dir: Path
    artifact: Path


def fail(message: str) -> None:
    raise UserError(message)


def command_text(command: Iterable[str]) -> str:
    return shlex.join(str(part) for part in command)


def run(command: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {command_text(command)}")
    result = subprocess.run(command, cwd=cwd, text=True)
    if check and result.returncode != 0:
        fail(f"コマンドが失敗しました（終了コード {result.returncode}）: {command_text(command)}")
    return result


def capture(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        fail(f"コマンドが失敗しました（終了コード {result.returncode}）: {command_text(command)}{suffix}")
    return result.stdout


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"{name}が見つかりません。インストールしてから再実行してください。")


def compose_config(compose_path: Path) -> dict[str, Any]:
    require_command("docker")
    output = capture(
        ["docker", "compose", "-f", str(compose_path), "config", "--format", "json"],
        cwd=compose_path.parent,
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        fail(f"docker compose configのJSONを解釈できません: {error}")
        raise AssertionError("unreachable")


def bind_sources(service: dict[str, Any]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for volume in service.get("volumes", []):
        if not isinstance(volume, dict) or volume.get("type") != "bind":
            continue
        target = volume.get("target")
        source = volume.get("source")
        if isinstance(target, str) and isinstance(source, str):
            sources[target] = Path(source).resolve()
    return sources


def load_compose(compose_arg: str) -> ComposeInfo:
    compose_path = Path(compose_arg).expanduser()
    if not compose_path.is_absolute():
        compose_path = (Path.cwd() / compose_path).resolve()
    if not compose_path.is_file():
        fail(f"Composeファイルが見つかりません: {compose_path}")

    document = compose_config(compose_path)
    services = document.get("services")
    if not isinstance(services, dict) or not services:
        fail(f"Composeファイルにserviceがありません: {compose_path}")
    if len(services) != 1:
        names = ", ".join(sorted(services))
        fail(f"serviceが複数あります。現状は1 serviceのComposeだけ対応しています: {names}")

    service_name, service = next(iter(services.items()))
    if not isinstance(service, dict):
        fail(f"service定義を解釈できません: {service_name}")
    sources = bind_sources(service)
    workspace = sources.get(CONTAINER_WORKSPACE)
    config = sources.get(CONTAINER_CONFIG)
    modules = sources.get(CONTAINER_MODULES)
    if workspace is None:
        fail(f"{CONTAINER_WORKSPACE}へのbind volumeがありません: {compose_path}")
    if config is None:
        fail(f"{CONTAINER_CONFIG}へのbind volumeがありません: {compose_path}")
    if not config.is_dir():
        fail(f"configディレクトリがありません: {config}")
    if not (config / "build.yaml").is_file():
        fail(f"build.yamlがありません: {config / 'build.yaml'}")
    if not workspace.is_dir():
        fail(f"workspaceディレクトリがありません: {workspace}")
    if modules is not None and not modules.is_dir():
        fail(f"modulesディレクトリがありません: {modules}")
    extra_modules: list[str] = []
    if (config / "zephyr/module.yml").is_file():
        extra_modules.append(CONTAINER_CONFIG)
    if modules is not None:
        module_files = sorted(modules.glob("*/zephyr/module.yml"))
        if (modules / "zephyr/module.yml").is_file():
            module_files.insert(0, modules / "zephyr/module.yml")
        for module_file in module_files:
            module_root = module_file.parent.parent
            relative_root = module_root.relative_to(modules)
            extra_modules.append(str(Path(CONTAINER_MODULES) / relative_root))
    return ComposeInfo(compose_path, service_name, workspace, config, modules, tuple(extra_modules))


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        fail("PythonのPyYAMLが必要です。`python3 -m pip install pyyaml`後に再実行してください。")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        fail(f"build.yamlを読み込めません: {error}")
    if not isinstance(data, dict):
        fail(f"build.yamlのルートがmappingではありません: {path}")
    return data


def as_string_list(value: Any, field: str, target_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(shlex.split(value)) if field == "cmake-args" else (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    fail(f"{target_name}の{field}は文字列または文字列配列で指定してください")
    raise AssertionError("unreachable")


def raw_targets(document: dict[str, Any]) -> list[dict[str, Any]]:
    include = document.get("include")
    if include is None:
        fail("build.yamlはinclude形式でターゲットを定義してください")
    if not isinstance(include, list) or not all(isinstance(item, dict) for item in include):
        fail("build.yamlのincludeはmappingの配列で指定してください")
    return include


def load_targets(config_host: Path) -> list[BuildTarget]:
    entries = raw_targets(load_yaml(config_host / "build.yaml"))
    targets: list[BuildTarget] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        artifact_name = entry.get("artifact-name")
        board = entry.get("board")
        shield = entry.get("shield")
        if not isinstance(artifact_name, str) or not artifact_name:
            fail(f"build.yamlのinclude[{index}]にartifact-nameがありません")
        if not TARGET_NAME_RE.fullmatch(artifact_name):
            fail(f"artifact-nameに使用できない文字があります: {artifact_name}")
        if artifact_name in seen:
            fail(f"artifact-nameが重複しています: {artifact_name}")
        if not isinstance(board, str) or not board:
            fail(f"{artifact_name}のboardがありません")
        if not isinstance(shield, str) or not shield:
            fail(f"{artifact_name}のshieldがありません")
        target = BuildTarget(
            artifact_name=artifact_name,
            board=board,
            shield=shield,
            snippets=as_string_list(entry.get("snippet"), "snippet", artifact_name),
            cmake_args=as_string_list(entry.get("cmake-args"), "cmake-args", artifact_name),
        )
        targets.append(target)
        seen.add(artifact_name)
    if not targets:
        fail("build.yamlにビルドターゲットがありません")
    return targets


def target_context(compose: ComposeInfo, target_name: str) -> TargetContext:
    targets = load_targets(compose.config_host)
    target = next((item for item in targets if item.artifact_name == target_name), None)
    if target is None:
        available = ", ".join(item.artifact_name for item in targets)
        fail(f"ターゲットが見つかりません: {target_name}（利用可能: {available}）")
    build_dir = compose.config_host / "build" / target.artifact_name
    return TargetContext(compose, target, build_dir, build_dir / "zephyr" / "zmk.uf2")


def list_targets(compose: ComposeInfo) -> None:
    for target in load_targets(compose.config_host):
        snippets = ", ".join(target.snippets) or "なし"
        print(f"{target.artifact_name}\tboard={target.board}\tshield={target.shield}\tsnippet={snippets}")


def west_command(context: TargetContext) -> list[str]:
    target = context.target
    command = [
        "west",
        "build",
        "--pristine=auto",
        "-s",
        f"{CONTAINER_WORKSPACE}/zmk/app",
        "-d",
        f"{CONTAINER_CONFIG}/build/{target.artifact_name}",
        "-b",
        target.board,
    ]
    for snippet in target.snippets:
        command.extend(["-S", snippet])
    command.extend(
        [
            "--",
            f"-DZMK_CONFIG={CONTAINER_CONFIG}/config",
        ]
    )
    if context.compose.extra_modules:
        command.append(f"-DZMK_EXTRA_MODULES={';'.join(context.compose.extra_modules)}")
    command.append(f"-DSHIELD={target.shield}")
    command.extend(target.cmake_args)
    return command


def compose_command(context: TargetContext, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(context.compose.path), *args]


def service_running(context: TargetContext) -> bool:
    result = subprocess.run(
        compose_command(context, "ps", "--status", "running", "-q", context.compose.service),
        cwd=context.compose.path.parent,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def wait_for_workspace(context: TargetContext, timeout: int = 180) -> None:
    check = compose_command(
        context,
        "exec",
        "-T",
        context.compose.service,
        "sh",
        "-c",
        "test -d /workspaces/zmk/.west && test -d /workspaces/zmk/zmk && test -d /workspaces/zmk/zephyr",
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(check, cwd=context.compose.path.parent, capture_output=True)
        if result.returncode == 0:
            return
        time.sleep(2)
    fail("Docker workspaceの初期化がタイムアウトしました。west updateのログを確認してください。")


def run_build(context: TargetContext, *, dry_run: bool, keep_container: bool) -> None:
    compose = context.compose
    started_by_us = False if dry_run else not service_running(context)
    try:
        if dry_run:
            print(f"$ {command_text(compose_command(context, 'up', '-d', compose.service))}")
            print(f"$ {command_text(compose_command(context, 'exec', '-T', compose.service, *west_command(context)))}")
            return
        if started_by_us:
            run(compose_command(context, "up", "-d", compose.service), cwd=compose.path.parent)
            wait_for_workspace(context)
        run(
            compose_command(context, "exec", "-T", compose.service, *west_command(context)),
            cwd=compose.path.parent,
        )
        if not context.artifact.is_file():
            fail(f"ビルドは成功しましたがUF2が見つかりません: {context.artifact}")
        print(f"UF2: {context.artifact} ({context.artifact.stat().st_size} bytes)")
    finally:
        if started_by_us and not keep_container and not dry_run:
            run(compose_command(context, "stop", compose.service), cwd=compose.path.parent, check=False)


def usb_candidates() -> list[Path]:
    user = os.environ.get("USER")
    if not user:
        return []
    media_root = Path("/media") / user / "XIAO-SENSE"
    if not media_root.is_dir():
        return []
    if not os.access(media_root, os.W_OK):
        return []
    if any((media_root / marker).is_file() for marker in USB_MARKERS):
        return [media_root]
    return []


def find_usb(*, no_wait: bool) -> Path:
    warned = False
    while True:
        candidates = usb_candidates()
        if len(candidates) == 1:
            print(f"USBデバイスを検出しました: {candidates[0]}")
            return candidates[0]
        if len(candidates) > 1:
            names = "\n".join(f"  - {path}" for path in candidates)
            fail(f"UF2デバイスが複数見つかりました。1台だけ接続してください。\n{names}")
        if no_wait:
            fail("キーボードがUSB接続されていません。")
        if not warned:
            print("キーボードがUSB接続されていません。ブートローダーモードで接続してください。")
            print("接続されるまで待機します。中止する場合はCtrl-Cを押してください。")
            warned = True
        time.sleep(2)


def flash_artifact(artifact: Path, mount: Path) -> None:
    if not mount.is_dir() or not os.access(mount, os.W_OK):
        fail(f"USBデバイスへ書き込めません: {mount}")
    partial = mount / f"{artifact.stem}.uf2.part"
    destination = mount / f"{artifact.stem}.uf2"
    try:
        with artifact.open("rb") as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(partial, destination)
        os.sync()
    except OSError as error:
        try:
            partial.unlink()
        except OSError:
            pass
        fail(f"UF2を書き込めません: {error}")
    print(f"書き込み完了: {destination}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Composeとbuild.yamlからZMKをビルド・書き込みします")
    parser.add_argument("command", choices=("build", "flash", "list-targets"))
    parser.add_argument("--compose", required=True, help="使用するdocker-composeファイル")
    parser.add_argument("--target", help="build.yamlのartifact-name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-container", action="store_true")
    parser.add_argument("--no-wait", action="store_true", help="USB未接続時に待機しない")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        compose = load_compose(args.compose)
        if args.command == "list-targets":
            list_targets(compose)
            return 0
        if not args.target:
            parser.error("buildまたはflashには--targetが必要です")
        context = target_context(compose, args.target)
        run_build(context, dry_run=args.dry_run, keep_container=args.keep_container)
        if args.command == "flash" and not args.dry_run:
            mount = find_usb(no_wait=args.no_wait)
            flash_artifact(context.artifact, mount)
        return 0
    except UserError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中止しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
