package ai.phronetic.screener.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface ScreenedCallDao {

    @Insert
    suspend fun insert(call: ScreenedCall): Long

    @Update
    suspend fun update(call: ScreenedCall)

    @Delete
    suspend fun delete(call: ScreenedCall)

    @Query("SELECT * FROM screened_calls ORDER BY timestamp DESC")
    fun getAll(): Flow<List<ScreenedCall>>

    @Query("SELECT * FROM screened_calls WHERE id = :id LIMIT 1")
    suspend fun getById(id: Long): ScreenedCall?

    @Query("SELECT * FROM screened_calls WHERE callerNumber = :number ORDER BY timestamp DESC")
    fun getByNumber(number: String): Flow<List<ScreenedCall>>

    @Query("SELECT * FROM screened_calls WHERE isSpam = 1 ORDER BY timestamp DESC")
    fun getSpamCalls(): Flow<List<ScreenedCall>>

    @Query("SELECT COUNT(*) FROM screened_calls")
    fun getCallCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM screened_calls WHERE isSpam = 1")
    fun getSpamCount(): Flow<Int>

    @Query("DELETE FROM screened_calls")
    suspend fun clearAll()
}
