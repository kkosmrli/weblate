# Copyright © Michal Čihař <michal@weblate.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from functools import reduce

from django.db.models import Count, Prefetch, Q
from django.utils.translation import gettext_lazy as _

from weblate.checks.base import TargetCheck
from weblate.utils.state import STATE_TRANSLATED


class PluralsCheck(TargetCheck):
    """Check for incomplete plural forms."""

    check_id = "plurals"
    name = _("Missing plurals")
    description = _("Some plural forms are untranslated")

    def should_skip(self, unit):
        if unit.translation.component.is_multivalue:
            return True
        return super().should_skip(unit)

    def check_target_unit(self, sources, targets, unit):
        # Is this plural?
        if len(sources) == 1:
            return False
        # Is at least something translated?
        if targets == len(targets) * [""]:
            return False
        # Check for empty translation
        return "" in targets

    def check_single(self, source, target, unit):
        """We don't check target strings here."""
        return False


class SamePluralsCheck(TargetCheck):
    """Check for same plural forms."""

    check_id = "same-plurals"
    name = _("Same plurals")
    description = _("Some plural forms are translated in the same way")

    def check_target_unit(self, sources, targets, unit):
        # Is this plural?
        if len(sources) == 1 or len(targets) == 1:
            return False
        if targets[0] == "":
            return False
        return len(set(targets)) == 1

    def check_single(self, source, target, unit):
        """We don't check target strings here."""
        return False


class ConsistencyCheck(TargetCheck):
    """Check for inconsistent translations."""

    check_id = "inconsistent"
    name = _("Inconsistent")
    description = _(
        "This string has more than one translation in this project "
        "or is untranslated in some components."
    )
    ignore_untranslated = False
    propagates = True
    batch_project_wide = True
    skip_suggestions = True

    def check_target_unit(self, sources, targets, unit):
        component = unit.translation.component
        if not component.allow_translation_propagation:
            return False

        # Use last result if checks are batched
        if component.batch_checks:
            return self.handle_batch(unit, component)

        for other in unit.same_source_units:
            if unit.target == other.target:
                continue
            if unit.translated or other.translated:
                return True
        return False

    def check_single(self, source, target, unit):
        """We don't check target strings here."""
        return False

    def check_component(self, component):
        from weblate.trans.models import Unit

        units = Unit.objects.filter(
            translation__component__project=component.project,
            translation__component__allow_translation_propagation=True,
        )

        # List strings with different targets
        # Limit this to 100 strings, otherwise the resulting query is way too complex
        matches = (
            units.values("id_hash", "translation__language", "translation__plural")
            .annotate(Count("target", distinct=True))
            .filter(target__count__gt=1)
            .order_by("id_hash")[:100]
        )

        if not matches:
            return []

        return (
            units.filter(
                reduce(
                    lambda x, y: x
                    | (
                        Q(id_hash=y["id_hash"])
                        & Q(translation__language=y["translation__language"])
                        & Q(translation__plural=y["translation__plural"])
                    ),
                    matches,
                    Q(),
                )
            )
            .prefetch()
            .prefetch_bulk()
        )


class TranslatedCheck(TargetCheck):
    """Check for inconsistent translations."""

    check_id = "translated"
    name = _("Has been translated")
    description = _("This string has been translated in the past")
    ignore_untranslated = False
    skip_suggestions = True

    def get_description(self, check_obj):
        unit = check_obj.unit
        target = self.check_target_unit(unit.source, unit.target, unit)
        if not target:
            return super().get_description(check_obj)
        return _('Previous translation was "%s".') % target

    @property
    def change_states(self):
        from weblate.trans.models import Change

        states = {Change.ACTION_SOURCE_CHANGE}
        states.update(Change.ACTIONS_CONTENT)
        return states

    def check_target_unit(self, sources, targets, unit):
        if unit.translated:
            return False

        component = unit.translation.component

        if component.batch_checks:
            return self.handle_batch(unit, component)

        from weblate.trans.models import Change

        changes = unit.change_set.filter(action__in=self.change_states).order()

        for action, target in changes.values_list("action", "target"):
            if action in Change.ACTIONS_CONTENT and target and target != unit.target:
                return target
            if action == Change.ACTION_SOURCE_CHANGE:
                break

        return False

    def check_single(self, source, target, unit):
        """We don't check target strings here."""
        return False

    def get_fixup(self, unit):
        target = self.check_target_unit(unit.source, unit.target, unit)
        if not target:
            return None
        return [(".*", target, "u")]

    def check_component(self, component):
        from weblate.trans.models import Change, Unit

        units = (
            Unit.objects.filter(
                translation__component=component,
                change__action__in=self.change_states,
                state__lt=STATE_TRANSLATED,
            )
            .prefetch_related(
                Prefetch(
                    "change_set",
                    queryset=Change.objects.filter(
                        action__in=self.change_states
                    ).order(),
                    to_attr="recent_consistency_changes",
                )
            )
            .prefetch()
            .prefetch_bulk()
        )

        for unit in units:
            for change in unit.recent_consistency_changes:
                if change.action in Change.ACTIONS_CONTENT and change.target:
                    yield unit
                if change.action == Change.ACTION_SOURCE_CHANGE:
                    break
