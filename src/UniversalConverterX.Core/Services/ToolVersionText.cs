namespace UniversalConverterX.Core.Services;

internal static class ToolVersionText
{
    public static string? ExtractFirstDottedToken(string? output)
    {
        if (string.IsNullOrWhiteSpace(output))
            return null;

        foreach (var line in output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = line.Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries);
            foreach (var part in parts)
            {
                var cleaned = part.Trim().Trim(',', '(', ')', '[', ']', ':', ';');
                if (cleaned.Length > 1
                    && cleaned[0] is 'n' or 'N' or 'v' or 'V'
                    && char.IsDigit(cleaned[1]))
                {
                    cleaned = cleaned[1..];
                }

                if (cleaned.Length > 0 && char.IsDigit(cleaned[0]) && cleaned.Contains('.'))
                    return cleaned;
            }
        }

        return null;
    }
}
