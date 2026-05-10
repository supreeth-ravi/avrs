package ai.phronetic.screener.data.db

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "contact_rules",
    indices = [Index(value = ["phoneNumber"], unique = true)]
)
data class ContactRule(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val phoneNumber: String,
    val name: String? = null,
    val type: RuleType,
    val createdAt: Long = System.currentTimeMillis()
) {
    enum class RuleType {
        WHITELIST,
        BLOCKLIST
    }
}
