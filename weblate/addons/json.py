# Copyright © Michal Čihař <michal@weblate.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from django.utils.translation import gettext_lazy as _

from weblate.addons.base import StoreBaseAddon
from weblate.addons.forms import JSONCustomizeForm


class JSONCustomizeAddon(StoreBaseAddon):
    name = "weblate.json.customize"
    verbose = _("Customize JSON output")
    description = _(
        "Allows adjusting JSON output behavior, for example indentation or sorting."
    )
    settings_form = JSONCustomizeForm
    compat = {
        "file_format": {
            "json",
            "json-nested",
            "webextension",
            "i18next",
            "arb",
            "go-i18n-json",
        }
    }

    def store_post_load(self, translation, store):
        config = self.instance.configuration
        style = config.get("style", "spaces")
        indent = int(config.get("indent", 4))
        if style == "spaces":
            store.store.dump_args["indent"] = indent
        else:
            store.store.dump_args["indent"] = "\t" * indent
        store.store.dump_args["sort_keys"] = bool(int(config.get("sort_keys", 0)))
