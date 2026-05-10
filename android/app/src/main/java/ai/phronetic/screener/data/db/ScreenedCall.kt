package ai.phronetic.screener.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "screened_calls")
data class ScreenedCall(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val callerNumber: String,
    val callerName: String? = null,
    val timestamp: Long = System.currentTimeMillis(),
    val durationMs: Long = 0,
    val intent: String = "unknown",
    val action: String = "continue",
    val transcriptJson: String = "[]",
    val isSpam: Boolean = false,
    val isBlocked: Boolean = false,
    val isWhitelisted: Boolean = false,
    val userTypedMessage: String? = null,
    val endedReason: String? = null
)
