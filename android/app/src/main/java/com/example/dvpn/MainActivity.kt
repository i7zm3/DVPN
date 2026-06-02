package com.example.dvpn

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File

class MainActivity : ComponentActivity() {
    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            startVpnService()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            DVPNAppContent(
                storageDir = applicationContext.filesDir,
                onStart = { requestVpnPermission() },
                onStop = { stopVpnService() }
            )
        }
    }

    private fun requestVpnPermission() {
        val prepareIntent = VpnService.prepare(this)
        if (prepareIntent != null) {
            vpnPermissionLauncher.launch(prepareIntent)
        } else {
            startVpnService()
        }
    }

    private fun startVpnService() {
        val intent = Intent(this, DVPNVpnService::class.java)
        startForegroundService(intent)
    }

    private fun stopVpnService() {
        val intent = Intent(this, DVPNVpnService::class.java).apply {
            action = DVPNVpnService.ACTION_STOP
        }
        startService(intent)
    }
}

@Composable
fun DVPNAppContent(storageDir: File, onStart: () -> Unit, onStop: () -> Unit) {
    var status by remember { mutableStateOf("stopped") }
    var logText by remember { mutableStateOf("Waiting for local log...\n") }
    val logFile = File(storageDir, "dvpn.log")

    LaunchedEffect(Unit) {
        while (true) {
            if (logFile.exists()) {
                logText = logFile.readText()
            }
            kotlinx.coroutines.delay(2000)
        }
    }

    Surface(color = MaterialTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(text = "DVPN", style = MaterialTheme.typography.h4)
            Text(text = "Status: $status", fontSize = 18.sp)
            Button(onClick = {
                status = "starting"
                onStart()
            }) {
                Text(text = "Start DVPN")
            }
            Button(onClick = {
                status = "stopped"
                onStop()
            }) {
                Text(text = "Stop DVPN")
            }
            Text(text = "Local logs:", fontSize = 16.sp)
            Text(text = logText, fontSize = 14.sp)
        }
    }
}
