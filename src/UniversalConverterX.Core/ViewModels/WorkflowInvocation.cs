namespace UniversalConverterX.Core.ViewModels;

public sealed record WorkflowInvocation(
    string Engine,
    IReadOnlyList<string> Arguments,
    string OutputPath);
