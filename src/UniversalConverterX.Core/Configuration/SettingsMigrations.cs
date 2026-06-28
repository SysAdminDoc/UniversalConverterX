using System.Text.Json.Nodes;

namespace UniversalConverterX.Core.Configuration;

/// <summary>
/// Schema migration table for <c>settings.json</c>. Each entry transforms
/// the JSON tree from version N to version N+1 in-place. Migrations are
/// applied in order until the target version is reached.
/// </summary>
/// <remarks>
/// Closes ROADMAP Item 53 (Tier 2). The motivation is the iter-1 wave that
/// flipped the <see cref="OverwriteBehavior"/> default from <c>Ask</c> to
/// <c>Never</c> for fresh installs while preserving persisted user
/// preferences. That worked because the JSON deserializer kept the value
/// verbatim — but the next time a field is renamed or an enum value is
/// removed, schema migration becomes mandatory rather than incidental.
///
/// Add a migration when:
///   - A property is RENAMED on <see cref="ConverterXOptions"/>.
///   - An enum VALUE is removed or renamed.
///   - The shape of a nested object changes (e.g. a string becomes an
///     object with sub-fields).
///
/// Do NOT add a migration when:
///   - A property is ADDED (deserializer leaves it at its C# default).
///   - A default value changes for fresh installs only (persisted values
///     are untouched).
///   - A property is REMOVED but its old value can be ignored safely
///     (deserializer drops unknown fields silently).
/// </remarks>
internal static class SettingsMigrations
{
    /// <summary>
    /// Ordered list of migration steps. Index N transforms a v(N+1) JSON
    /// tree into a v(N+2) tree (i.e. <c>Migrations[0]</c> is v1 → v2).
    /// </summary>
    /// <remarks>
    /// History:
    ///   v1 → v2 (2026-05-02): no rename / rewrite needed. Adds the
    ///   <c>SchemaVersion</c> field if missing; legacy files lacked it
    ///   entirely.
    ///   v2 → v3 (2026-06-28): PostConversionAction replaces
    ///   DeleteSourceOnSuccess. If the legacy bool is true and the new
    ///   enum is absent, inject <c>"PostConversionAction": "Delete"</c>.
    /// </remarks>
    private static readonly List<Action<JsonObject>> Migrations =
    [
        // v1 -> v2: stamp the SchemaVersion field. No other rewrites.
        v1 => { /* no-op rename — SchemaVersion is set after migration runs */ },

        // v2 -> v3: migrate DeleteSourceOnSuccess=true → PostConversionAction=Delete.
        v2 =>
        {
            if (v2["PostConversionAction"] is not null)
                return;
            var legacy = v2["DeleteSourceOnSuccess"];
            if (legacy is JsonValue jv && jv.TryGetValue<bool>(out var del) && del)
            {
                v2["PostConversionAction"] = "Delete";
            }
        },
    ];

    /// <summary>
    /// Apply migrations in order to bring <paramref name="root"/> from
    /// <paramref name="fromVersion"/> up to <paramref name="toVersion"/>.
    /// Returns the (possibly mutated) root and sets
    /// <paramref name="didMigrate"/> when at least one migration ran.
    /// </summary>
    /// <remarks>
    /// Future versions newer than <paramref name="toVersion"/> are left
    /// alone — older binaries should refuse the file rather than silently
    /// downgrade. The deserializer will keep whatever fields it understands
    /// and ignore the rest.
    /// </remarks>
    public static JsonObject Migrate(JsonObject root, int fromVersion, int toVersion,
                                     out bool didMigrate)
    {
        didMigrate = false;

        if (fromVersion >= toVersion)
            return root;

        for (var v = fromVersion; v < toVersion; v++)
        {
            var migrationIndex = v - 1;
            if (migrationIndex < 0 || migrationIndex >= Migrations.Count)
            {
                // Gap in the migration table — fall back to "stamp the version"
                // so we don't loop forever. Surfaces as a no-op upgrade.
                break;
            }
            Migrations[migrationIndex](root);
            didMigrate = true;
        }

        // Stamp the post-migration version so the loaded options carries it.
        root["SchemaVersion"] = toVersion;
        return root;
    }
}
