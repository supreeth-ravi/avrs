package ai.phronetic.screener.ui.screens

import androidx.compose.animation.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ai.phronetic.screener.data.db.ContactRule
import ai.phronetic.screener.ui.*
import ai.phronetic.screener.viewmodel.ContactsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ContactsScreen(vm: ContactsViewModel = viewModel()) {
    val whitelist by vm.whitelist.collectAsStateWithLifecycle()
    val blocklist by vm.blocklist.collectAsStateWithLifecycle()
    var selectedTab by remember { mutableStateOf(0) }
    var showAddDialog by remember { mutableStateOf(false) }
    val tabs = listOf("Whitelist", "Blocklist")

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDark)
    ) {
        TopAppBar(
            title = { Text("Contacts", color = TextPrimary) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = Surface1),
            actions = {
                IconButton(onClick = { showAddDialog = true }) {
                    Icon(Icons.Default.Add, contentDescription = "Add", tint = VioletLight)
                }
            }
        )

        TabRow(
            selectedTabIndex = selectedTab,
            containerColor = Surface1,
            contentColor = VioletLight,
            divider = { Divider(color = Border) }
        ) {
            tabs.forEachIndexed { index, title ->
                Tab(
                    selected = selectedTab == index,
                    onClick = { selectedTab = index },
                    text = { Text(title, fontSize = 14.sp) }
                )
            }
        }

        val items = if (selectedTab == 0) whitelist else blocklist

        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
        ) {
            if (items.isEmpty()) {
                EmptyState(
                    message = if (selectedTab == 0)
                        "No whitelisted contacts\nThese numbers will always ring through"
                    else
                        "No blocked contacts\nThese numbers will be silently rejected"
                )
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(items.size, key = { items[it].id }) { index ->
                        val rule = items[index]
                        RuleListItem(rule = rule, onDelete = { vm.removeRule(rule) })
                    }
                }
            }
        }
    }

    if (showAddDialog) {
        AddRuleDialog(
            type = if (selectedTab == 0) ContactRule.RuleType.WHITELIST else ContactRule.RuleType.BLOCKLIST,
            onDismiss = { showAddDialog = false },
            onAdd = { number, name ->
                if (selectedTab == 0) vm.addToWhitelist(number, name)
                else vm.addToBlocklist(number, name)
                showAddDialog = false
            }
        )
    }
}

@Composable
fun RuleListItem(rule: ContactRule, onDelete: () -> Unit) {
    val color = if (rule.type == ContactRule.RuleType.WHITELIST) Emerald else Rose

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = Surface1,
        border = BorderStroke(1.dp, Border)
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(color.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    rule.name?.firstOrNull()?.toString() ?: "#",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                    color = color
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    rule.name ?: rule.phoneNumber,
                    fontWeight = FontWeight.SemiBold,
                    color = TextPrimary,
                    fontSize = 15.sp
                )
                if (rule.name != null) {
                    Text(rule.phoneNumber, fontSize = 12.sp, color = TextMuted)
                }
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "Remove", tint = Rose)
            }
        }
    }
}

@Composable
fun AddRuleDialog(
    type: ContactRule.RuleType,
    onDismiss: () -> Unit,
    onAdd: (String, String?) -> Unit
) {
    var number by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    val isValid = number.length >= 10

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Surface1,
        title = {
            Text(
                if (type == ContactRule.RuleType.WHITELIST) "Add to Whitelist" else "Add to Blocklist",
                color = TextPrimary
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = number,
                    onValueChange = { number = it.filter { c -> c.isDigit() || c == '+' } },
                    label = { Text("Phone number", color = TextMuted) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    )
                )
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Name (optional)", color = TextMuted) },
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Violet,
                        unfocusedBorderColor = Border,
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary
                    )
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onAdd(number, name.takeIf { it.isNotBlank() }) },
                enabled = isValid,
                colors = ButtonDefaults.buttonColors(containerColor = Violet)
            ) {
                Text("Add", color = Color.White)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel", color = TextMuted)
            }
        }
    )
}
