# zmk-firmware-build

This repository is a workspace for building ZMK firmware with Docker Compose.

The repository does not track fetched ZMK/Zephyr source trees or build artifacts. It only tracks the Compose definitions, container initialization files, and keyboard-specific `west build` helper scripts.

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

Run the appropriate script inside the container.

### Rokibo

```sh
./scripts/rokibo_l.sh
./scripts/rokibo_r.sh
./scripts/rokibo_reset.sh
```

| Script | Shield | Output directory |
| --- | --- | --- |
| `scripts/rokibo_l.sh` | `rokibo_left` | `/workspaces/zmk-config/build/left` |
| `scripts/rokibo_r.sh` | `rokibo_right` | `/workspaces/zmk-config/build/right` |
| `scripts/rokibo_reset.sh` | `settings_reset` | `/workspaces/zmk-config/build/reset` |

### roBa

```sh
./scripts/roba_l.sh
./scripts/roba_r.sh
```

| Script | Shield | Output directory |
| --- | --- | --- |
| `scripts/roba_l.sh` | `roBa_L` | `/workspaces/zmk-config/build/left` |
| `scripts/roba_r.sh` | `roBa_R` | `/workspaces/zmk-config/build/right` |

All build scripts target the `seeeduino_xiao_ble` board and enable the `studio-rpc-usb-uart` snippet.

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
