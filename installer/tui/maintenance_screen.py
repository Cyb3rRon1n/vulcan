from smithy import ConfirmRunScreen
from textual.widgets import Checkbox

from installer.generate import STACK_DIR
from installer.post_install import backup_stack, pull_stack, update_stack, uninstall_stack
from installer.self_update import update_vulcan_self


class MaintenanceScreen(ConfirmRunScreen):
    """
    Update/Pull/Backup/Uninstall/Update-Vulcan share an identical shape
    - confirm, run in a background worker, show the result, offer a
    way back to the Main Menu - which is exactly what smithy's
    ConfirmRunScreen already provides. This subclass exists purely to
    hold the classmethod factories below (one parametrized screen
    kept, rather than five near-duplicate ones), not to override any
    of ConfirmRunScreen's own behavior.
    """

    @classmethod
    def for_update(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Update Stack",
            confirm_text=f"This will pull the latest images and recreate containers for {compose_path}.",
            action=lambda: update_stack(str(compose_path), str(env_path)),
            success_message=lambda result: "Stack updated.",
        )

    @classmethod
    def for_pull(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Pull Images",
            confirm_text=f"This will pull images for {compose_path} without starting anything.",
            action=lambda: pull_stack(str(compose_path), str(env_path)),
            success_message=lambda result: "Images pulled.",
        )

    @classmethod
    def for_backup(cls) -> "MaintenanceScreen":

        return cls(
            title="Backup Stack",
            confirm_text="This will archive stack/config/ and the compose/env files to backups/.",
            action=lambda: backup_stack(),
            success_message=lambda result: "\n".join(
                [f"Backup written to {result['backup_path']}"]
                + [f"! {warning}" for warning in result.get("warnings", [])]
            ),
        )

    @classmethod
    def for_uninstall(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Uninstall Stack",
            confirm_text=(
                f"This will stop the running stack (if any) and permanently delete {STACK_DIR}/ "
                "(containers, network, and all app config/data). Your media library is always "
                "left untouched."
            ),
            # resolve_action, not a plain action - whether to also
            # purge backups/exports isn't known until the checkbox
            # below is read, which can't happen until the screen is
            # actually showing. Runs on the main thread (see
            # ConfirmRunScreen's own docstring for why that matters).
            resolve_action=lambda screen: (
                lambda: uninstall_stack(
                    str(compose_path), str(env_path),
                    purge_artifacts=screen.query_one("#purge-artifacts", Checkbox).value
                )
            ),
            success_message=lambda result: "Stack removed. Run `./install` again for a fresh setup.",
            extra_widget=Checkbox(
                "Also delete backups/ and exports/", value=False, id="purge-artifacts",
                tooltip="Leave unchecked to keep your backup/export archives after uninstalling."
            ),
        )

    @classmethod
    def for_update_self(cls) -> "MaintenanceScreen":
        """
        Updates Vulcan itself (this checkout), not a generated stack -
        found missing while researching DockSTARTer's own persistent
        Main Menu, which has an "Update DockSTARTer" item with no
        Vulcan equivalent before this. Always enabled (no stack_exists
        gate) - update_vulcan_self() itself cleanly refuses if this
        isn't a real git checkout.
        """

        return cls(
            title="Update Vulcan",
            confirm_text="This will fast-forward this Vulcan checkout to the latest origin/main.",
            action=update_vulcan_self,
            success_message=lambda result: (
                f"Updated {result['old_commit']} -> {result['new_commit']}. "
                "Restart Vulcan to use the new version."
                if result["updated"]
                else f"Already up to date ({result['commit']})."
            ),
        )
