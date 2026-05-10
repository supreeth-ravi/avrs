package ai.phronetic.screener.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface ContactRuleDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(rule: ContactRule): Long

    @Delete
    suspend fun delete(rule: ContactRule)

    @Query("SELECT * FROM contact_rules WHERE type = 'WHITELIST' ORDER BY createdAt DESC")
    fun getWhitelist(): Flow<List<ContactRule>>

    @Query("SELECT * FROM contact_rules WHERE type = 'BLOCKLIST' ORDER BY createdAt DESC")
    fun getBlocklist(): Flow<List<ContactRule>>

    @Query("SELECT * FROM contact_rules ORDER BY createdAt DESC")
    fun getAll(): Flow<List<ContactRule>>

    @Query("SELECT EXISTS(SELECT 1 FROM contact_rules WHERE phoneNumber = :number AND type = 'WHITELIST' LIMIT 1)")
    fun isWhitelisted(number: String): Boolean

    @Query("SELECT EXISTS(SELECT 1 FROM contact_rules WHERE phoneNumber = :number AND type = 'BLOCKLIST' LIMIT 1)")
    fun isBlocked(number: String): Boolean

    @Query("SELECT * FROM contact_rules WHERE phoneNumber = :number LIMIT 1")
    suspend fun getByNumber(number: String): ContactRule?

    @Query("DELETE FROM contact_rules WHERE phoneNumber = :number")
    suspend fun deleteByNumber(number: String)
}
