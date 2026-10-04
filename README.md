# zmk-firmware-build

This repository is a workspace for building ZMK firmware with Docker Compose.

The repository does not track fetched ZMK/Zephyr source trees or build artifacts. Compose files and each config repository's `build.yaml` are the source of truth for local builds.

## Requirements

- Docker, or a Docker-compatible Compose environment
- ZMK config and additional module directories placed next to this repository

For Rokibo:

```text
../zmk-config-rokibo
../zmk-modules
```

For roBa:

```text
../zmk-config-roBa
../zmk-modules
```

## Container

The default `docker-compose.yml` is for Rokibo.

```sh
docker compose up -d
docker compose exec zmk-rokibo bash
```

For roBa, specify the roBa Compose file.

```sh
docker compose -f docker-compose-roBa.yml up -d
docker compose -f docker-compose-roBa.yml exec zmk-rokibo bash
```

Both Compose files use `docker.io/zmkfirmware/zmk-dev-arm:3.5` and mount this repository at `/workspaces/zmk`. When the container starts, `root/entrypoint.sh` runs and initializes the workspace when needed:

- `west init -l config --mf /workspaces/zmk-config/config/west.yml`
- `west update --fetch-opt=--filter=blob:none`
- `west zephyr-export`

## Build

Use the generic CLI. It reads the service and bind mounts from the Compose file, then reads `board`, `shield`, `snippet`, `cmake-args`, and `artifact-name` from the mounted config's `build.yaml`.

PyYAML is required on the host:

```sh
python3 -m pip install pyyaml
```

List targets:

```sh
./scripts/zmk-build.sh list-targets \
  --compose docker-compose-rokibo_0.yml
```

Build one target:

```sh
./scripts/zmk-build.sh \
  --compose docker-compose-rokibo_0.yml \
  --target rokibo_0-right
```

The UF2 is expected at:

```text
../zmk-config-rokibo_0/build/rokibo_0-right/zephyr/zmk.uf2
```

Preview the generated Docker and west commands without starting Docker:

```sh
./scripts/zmk-build.sh \
  --compose docker-compose-rokibo_0.yml \
  --target rokibo_0-right \
  --dry-run
```

## Build and flash

Build and copy the UF2 to `/media/$USER/XIAO-SENSE/zmk.uf2` or `/run/media/$USER/XIAO-SENSE/zmk.uf2`:

```sh
./scripts/zmk-flash.sh \
  --compose docker-compose-rokibo_0.yml \
  --target rokibo_0-right
```

If no keyboard is connected, the command warns and waits. Use `--no-wait` to exit immediately instead. The script writes only when either mount point is writable and contains `INFO_UF2.TXT` or `CURRENT.UF2`. Before writing, an existing `zmk.uf2` is backed up to `/tmp/zmk-uf2-backup-*.uf2`.

For `zmk-config-rokibo_0`, the current targets are:

| Target | Board | Shield | Snippet |
| --- | --- | --- | --- |
| `rokibo_0-right` | `seeeduino_xiao_ble` | `rokibo_0_right rgbled_adapter` | `studio-rpc-usb-uart` |
| `rokibo_0-left` | `seeeduino_xiao_ble` | `rokibo_0_left rgbled_adapter` | none |
| `rokibo_0-reset` | `seeeduino_xiao_ble` | `settings_reset` | none |

Each entry must have a unique, path-safe `artifact-name`. Add a new device by adding a Compose file and a config repository with `build.yaml`; do not add a device-specific west script.

The old `rokibo0_l.sh`, `rokibo0_r.sh`, and `rokibo0_reset.sh` files remain as compatibility wrappers.

## Generated Files

The `.gitignore` excludes west workspace metadata, fetched ZMK/Zephyr source trees, additional modules, and working files under `root`:

```text
/.west
/zephyr
/zmk
/zmk-*
/modules
/root/*
```

As exceptions, `root/.bashrc` and `root/entrypoint.sh` are tracked because they are required by the container setup.

## Shutdown

```sh
docker compose down
```

If the roBa Compose file was used:

```sh
docker compose -f docker-compose-roBa.yml down
```
