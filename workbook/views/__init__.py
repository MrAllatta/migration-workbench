"""View archetype packages.

Each sub-package implements one view archetype (checklist, landing, dashboard,
list, with reference and print coming next).  The :mod:`workbook.views.registry`
module maps archetype labels to these packages so that ``generate_views`` can
dispatch by label instead of hard-coding imports.

Import from the individual sub-packages:

    from workbook.views.checklist import ChecklistArchetype
    from workbook.views.landing import LandingArchetype
    from workbook.views.dashboard import DashboardArchetype
    from workbook.views.list import ListArchetype

Or use the registry for dynamic dispatch:

    from workbook.views import registry
    module = registry.load("checklist")
    source = module.render_checklist_view_py(archetype)
"""
