package ai.phronetic.screener.engine

data class ScreeningResult(
    val spokenText: String,
    val intent: String,      // spam | delivery | work | personal | emergency | unknown
    val action: String,      // continue | end_call | flag_urgent
    val corpusKey: String?,  // key into bundled corpus WAV assets, null = use TTS
)

interface ScreeningEngine {
    /** Given the conversation so far, produce the next screener response. */
    fun respond(history: List<Turn>): ScreeningResult
}

data class Turn(val role: String, val text: String)  // role = "caller" | "assistant"
