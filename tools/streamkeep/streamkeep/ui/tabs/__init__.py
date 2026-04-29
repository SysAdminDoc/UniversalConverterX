"""Per-tab page builders. Each `build_*_tab(win)` takes the StreamKeep
main window instance, builds its widget tree, stashes widget references
on `win.*` attributes (so the existing handler methods on StreamKeep
keep working), and returns the page widget."""
