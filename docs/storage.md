# Storage Planning

For a fresh machine with drives that aren't set up yet - detects what's really there and computes the exact commands a RAID + mount setup would need, without running any of them:

```bash
vulcan storage report                                    # list real block devices, flag which are protected
vulcan storage plan --devices /dev/sdb,/dev/sdc           # compute a plan (mdadm RAID + format + mount)
```

`vulcan storage report` is always safe - it only reads (`lsblk`, `findmnt`), never plans or touches anything. Any device currently backing `/`, `/boot`, or `/boot/efi` is flagged `protected`.

`vulcan storage plan` takes one or more device paths and computes what provisioning them as a single mounted volume would look like: one device gets formatted and mounted directly; two or more get pooled into a real `mdadm` RAID array first (RAID1 for exactly 2 devices, RAID5 for 3+, or pass `--raid-level` to choose explicitly - mdadm's own real device-count minimums are enforced, not invented).

!!! danger "A protected device can never be selected as a target - there is no override flag."
    A device that already has a filesystem or partition table is flagged in the plan's output (it would be erased), not silently overwritten.

!!! info "This command only ever prints what would happen — nothing is executed."
    No `--yes`/`--non-interactive` flag exists here because there's nothing to confirm yet; real execution (an actual `mdadm --create`/`mkfs`/`mount` run) is a deliberate, separate, more heavily-gated piece of work Vulcan doesn't do yet - see the [Roadmap](roadmap.md).

## Why one pooled volume, not one drive per media category

Media categories (TV, Movies, Music, Books) don't need separate storage to stay organized - every generated stack already creates them as real subdirectories (`media/tv`, `media/movies`, etc.) under one pooled `MEDIA_PATH`, which is deliberate: `*arr` apps import via hardlink (instant, no duplicate disk usage) rather than copying, and hardlinks can't cross filesystems - splitting categories onto genuinely separate physical drives would silently turn every import into a slow copy instead. When planning storage, aim for one well-sized pooled volume, not one drive per category.
