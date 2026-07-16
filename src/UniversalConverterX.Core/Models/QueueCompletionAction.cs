using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Models;

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum QueueCompletionAction
{
    None,
    Notify,
    Sleep,
    Shutdown,
    RunScript,
}

[JsonConverter(typeof(JsonStringEnumConverter))]
public enum QueueCompletionItemStatus
{
    Succeeded,
    Failed,
    Cancelled,
}
