package ai.phronetic.screener.data.repository

import ai.phronetic.screener.data.db.ScreenedCall
import ai.phronetic.screener.data.db.ScreenedCallDao
import kotlinx.coroutines.flow.Flow

class CallHistoryRepository(private val dao: ScreenedCallDao) {

    val allCalls: Flow<List<ScreenedCall>> = dao.getAll()
    val spamCalls: Flow<List<ScreenedCall>> = dao.getSpamCalls()
    val callCount: Flow<Int> = dao.getCallCount()
    val spamCount: Flow<Int> = dao.getSpamCount()

    suspend fun insert(call: ScreenedCall): Long = dao.insert(call)

    suspend fun update(call: ScreenedCall) = dao.update(call)

    suspend fun delete(call: ScreenedCall) = dao.delete(call)

    fun getByNumber(number: String): Flow<List<ScreenedCall>> = dao.getByNumber(number)

    suspend fun getById(id: Long): ScreenedCall? = dao.getById(id)

    suspend fun clearAll() = dao.clearAll()
}
