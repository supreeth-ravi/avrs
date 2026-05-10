package ai.phronetic.screener.ui

import android.Manifest
import android.app.role.RoleManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import ai.phronetic.screener.Config
import ai.phronetic.screener.ui.screens.DashboardScreen
import ai.phronetic.screener.ui.screens.HistoryScreen
import ai.phronetic.screener.ui.screens.ContactsScreen
import ai.phronetic.screener.ui.screens.ProfileScreen
import ai.phronetic.screener.ui.screens.OnboardingScreen
import ai.phronetic.screener.viewmodel.DashboardViewModel
import kotlinx.coroutines.delay

// ── Palette ──────────────────────────────────────────────────────────────────
val BgDark      = Color(0xFF08080F)
val Surface1    = Color(0xFF111120)
val Surface2    = Color(0xFF1A1A2E)
val Violet      = Color(0xFF7C3AED)
val VioletLight = Color(0xFFAB72FF)
val Cyan        = Color(0xFF06B6D4)
val Emerald     = Color(0xFF10B981)
val Rose        = Color(0xFFE11D48)
val Amber       = Color(0xFFF59E0B)
val TextPrimary = Color(0xFFF0F0FF)
val TextMuted   = Color(0xFF6666AA)
val Border      = Color(0xFF2A2A40)

@OptIn(ExperimentalMaterial3Api::class)
class MainActivity : ComponentActivity() {

    private val requestPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* checked in onboarding */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ScreenerTheme {
                val navController = rememberNavController()
                val navBackStackEntry by navController.currentBackStackEntryAsState()
                val currentDestination = navBackStackEntry?.destination

                val showOnboarding = !Config.isOnboarded(this)

                if (showOnboarding) {
                    OnboardingScreen(
                        onComplete = {
                            Config.setOnboarded(this, true)
                            recreate()
                        }
                    )
                } else {
                    Scaffold(
                        containerColor = BgDark,
                        bottomBar = {
                            NavigationBar(
                                containerColor = Surface1,
                                tonalElevation = 0.dp
                            ) {
                                val items = listOf(
                                    Screen.Dashboard to Icons.Default.Home,
                                    Screen.History to Icons.Default.Info,
                                    Screen.Contacts to Icons.Default.Person,
                                    Screen.Profile to Icons.Default.AccountCircle,
                                )
                                items.forEach { (screen, icon) ->
                                    val selected = currentDestination?.hierarchy?.any { it.route == screen.route } == true
                                    NavigationBarItem(
                                        icon = { Icon(icon, contentDescription = screen.title) },
                                        label = { Text(screen.title, fontSize = 11.sp) },
                                        selected = selected,
                                        onClick = {
                                            navController.navigate(screen.route) {
                                                popUpTo(navController.graph.findStartDestination().id) {
                                                    saveState = true
                                                }
                                                launchSingleTop = true
                                                restoreState = true
                                            }
                                        },
                                        colors = NavigationBarItemDefaults.colors(
                                            selectedIconColor = VioletLight,
                                            selectedTextColor = VioletLight,
                                            unselectedIconColor = TextMuted,
                                            unselectedTextColor = TextMuted,
                                            indicatorColor = Surface2
                                        )
                                    )
                                }
                            }
                        }
                    ) { innerPadding ->
                        NavHost(
                            navController = navController,
                            startDestination = Screen.Dashboard.route,
                            modifier = Modifier.padding(innerPadding)
                        ) {
                            composable(Screen.Dashboard.route) { DashboardScreen() }
                            composable(Screen.History.route) { HistoryScreen() }
                            composable(Screen.Contacts.route) { ContactsScreen() }
                            composable(Screen.Profile.route) { ProfileScreen() }
                        }
                    }
                }
            }
        }
    }
}

sealed class Screen(val route: String, val title: String) {
    object Dashboard : Screen("dashboard", "Home")
    object History : Screen("history", "History")
    object Contacts : Screen("contacts", "Contacts")
    object Profile : Screen("profile", "Profile")
}

@Composable
fun ScreenerTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            background   = BgDark,
            surface      = Surface1,
            primary      = Violet,
            onBackground = TextPrimary,
            onSurface    = TextPrimary,
        ),
        content = content,
    )
}
