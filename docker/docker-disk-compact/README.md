# Docker Disk Compact

`docker-disk-compact.zsh` reclaims Docker Desktop disk space on macOS and reports the real on-disk size of `Docker.raw` before and after cleanup.

The main point of the utility is to avoid the misleading `ls -lh` view of `Docker.raw`. Docker Desktop stores data in a sparse disk image, so the logical size can stay large even after reclaimable data has been removed. This script measures physical disk usage with `du` and `stat`, then runs the Docker cleanup steps that actually mattered in practice.

## Files

- `docker-disk-compact.zsh` - Zsh script for pruning unused Docker data and reporting before/after disk usage.

## What It Does

Safe default behavior:

1. Locates the Docker Desktop `Docker.raw` disk image.
2. Reports physical size on disk and logical max size.
3. Runs `docker builder prune -a -f`.
4. Runs `docker system prune -f`.
5. Reports the updated physical size and the reclaimed amount.

Optional behavior:

- `--aggressive` also runs `docker image prune -a -f`.
- `--with-volumes` also runs `docker volume prune -f`.
- `--with-desktop-reclaim` runs `docker/desktop-reclaim-space` as a best-effort extra compaction step.
- `--dry-run` prints the commands without executing them.

## Requirements

- macOS
- Docker Desktop running
- `docker` CLI available in `PATH`
- `zsh`

## Usage

Run the safe default cleanup:

```sh
./docker-disk-compact.zsh
```

Preview actions without changing anything:

```sh
./docker-disk-compact.zsh --dry-run
```

Include additional cleanup:

```sh
./docker-disk-compact.zsh --aggressive --with-volumes --with-desktop-reclaim
```

## Notes

- `ls -lh ~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` shows the logical size, not actual disk consumption.
- `du -h` is the useful measure when you want to know how much SSD space Docker Desktop is really using.
- Volumes are not pruned by default because they are often the highest-risk data to delete accidentally.
