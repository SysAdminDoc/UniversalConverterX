using System.Text;

namespace UniversalConverterX.Core.Localization;

/// <summary>
/// Produces an intentionally expanded pseudo-locale string for UI layout
/// checks. Format placeholders and path-like values inside braces remain
/// unchanged so the result still exercises the same resource contract.
/// </summary>
public static class PseudoLocalization
{
    private static readonly IReadOnlyDictionary<char, string> Replacements =
        new Dictionary<char, string>
        {
            ['A'] = "Ȧ", ['a'] = "ȧ",
            ['B'] = "Ƃ", ['b'] = "ƀ",
            ['C'] = "Ć", ['c'] = "ć",
            ['D'] = "Ḋ", ['d'] = "ḋ",
            ['E'] = "Ē", ['e'] = "ē",
            ['F'] = "Ḟ", ['f'] = "ḟ",
            ['G'] = "Ġ", ['g'] = "ġ",
            ['H'] = "Ḧ", ['h'] = "ḧ",
            ['I'] = "Ī", ['i'] = "ī",
            ['J'] = "Ĵ", ['j'] = "ĵ",
            ['K'] = "Ḱ", ['k'] = "ḱ",
            ['L'] = "Ŀ", ['l'] = "ŀ",
            ['M'] = "Ṁ", ['m'] = "ṁ",
            ['N'] = "Ń", ['n'] = "ń",
            ['O'] = "Ō", ['o'] = "ō",
            ['P'] = "Ṕ", ['p'] = "ṕ",
            ['Q'] = "Ɋ", ['q'] = "ɋ",
            ['R'] = "Ŕ", ['r'] = "ŕ",
            ['S'] = "Ś", ['s'] = "ś",
            ['T'] = "Ṫ", ['t'] = "ṫ",
            ['U'] = "Ū", ['u'] = "ū",
            ['V'] = "Ṿ", ['v'] = "ṿ",
            ['W'] = "Ẇ", ['w'] = "ẇ",
            ['X'] = "Ẋ", ['x'] = "ẋ",
            ['Y'] = "Ŷ", ['y'] = "ŷ",
            ['Z'] = "Ż", ['z'] = "ż",
        };

    public static string Transform(string value)
    {
        if (string.IsNullOrEmpty(value))
            return value;

        var builder = new StringBuilder(value.Length + 8);
        var inPlaceholder = false;
        foreach (var character in value)
        {
            if (character == '{')
                inPlaceholder = true;
            else if (character == '}')
                inPlaceholder = false;

            if (!inPlaceholder && Replacements.TryGetValue(character, out var replacement))
                builder.Append(replacement);
            else
                builder.Append(character);
        }

        // Delimiters make pseudo-localized values unmistakable in UIA dumps,
        // while the repeated middle dot provides a modest width expansion.
        return $"［{builder}··］";
    }
}
