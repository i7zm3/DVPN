package com.example.dvpn

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

class DVPNVpnService : VpnService() {
    companion object {
        const val CHANNEL_ID = "dvpn_channel"
        const val NOTIFICATION_ID = 1001
        const val ACTION_STOP = "com.example.dvpn.action.STOP"
    }

    private var vpnInterface: ParcelFileDescriptor? = null
    private var serviceJob: Job? = null
    private val running = AtomicBoolean(false)
    private lateinit var logFile: File
    private var discovery: PeerDiscovery? = null
    private lateinit var keyPair: KeyPair

    override fun onCreate() {
        super.onCreate()
        logFile = File(filesDir, "dvpn.log")
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        if (running.compareAndSet(false, true)) {
            startForeground(NOTIFICATION_ID, buildNotification("DVPN starting"))
            serviceJob = CoroutineScope(Dispatchers.IO).launch {
                try {
                    startVpn()
                    log("VPN tunnel ready")
                } catch (error: Exception) {
                    log("VPN startup failed: ${error.message}")
                    stopSelf()
                }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopVpn()
        super.onDestroy()
    }

    private fun startVpn() {
        keyPair = generateKeyPair()
        vpnInterface = buildVpn() ?: throw IllegalStateException("Failed to create VPN interface")
        log("Generated endpoint keys and established VPN interface")

        discovery = PeerDiscovery(this, 10000, keyPair.public.encoded.encodeToString())
        discovery?.start()
    }

    private fun stopVpn() {
        running.set(false)
        discovery?.stop()
        discovery = null
        vpnInterface?.close()
        vpnInterface = null
        log("VPN stopped")
    }

    private fun buildVpn(): ParcelFileDescriptor? {
        val builder = Builder()
            .setSession("DVPN")
            .addAddress("10.99.99.2", 24)
            .addRoute("0.0.0.0", 0)
            .setBlocking(true)

        return builder.establish()
    }

    private fun generateKeyPair(): KeyPair {
        val generator = KeyPairGenerator.getInstance("X25519")
        return generator.generateKeyPair()
    }

    private fun buildNotification(message: String) =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("DVPN")
            .setContentText(message)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setOngoing(true)
            .setContentIntent(
                PendingIntent.getActivity(
                    this,
                    0,
                    Intent(this, MainActivity::class.java),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
                )
            )
            .build()

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "DVPN Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "DVPN foreground service channel"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun log(message: String) {
        logFile.appendText("${System.currentTimeMillis()} - $message\n")
    }
}

private fun ByteArray.encodeToString(): String = android.util.Base64.encodeToString(this, android.util.Base64.NO_WRAP)

private class PeerDiscovery(
    private val context: Context,
    private val port: Int,
    private val publicKey: String
) {
    private val running = AtomicBoolean(false)
    private var socket: DatagramSocket? = null
    private val peers = ConcurrentHashMap<String, PeerEntry>()
    private val logFile by lazy { File(context.filesDir, "dvpn.log") }

    fun start() {
        running.set(true)
        Thread {
            try {
                socket = DatagramSocket(port).apply {
                    broadcast = true
                    soTimeout = 2000
                }
                log("Peer discovery started on port $port")
                val address = broadcastAddress()
                while (running.get()) {
                    try {
                        val message = JSONObject().apply {
                            put("node_id", java.util.UUID.randomUUID().toString())
                            put("public_key", publicKey)
                            put("endpoint", "${localAddress()}:$port")
                        }.toString().toByteArray(Charsets.UTF_8)
                        socket?.send(DatagramPacket(message, message.size, address, port))
                    } catch (error: Exception) {
                        log("Broadcast failed: ${error.message}")
                    }

                    try {
                        val buffer = ByteArray(1024)
                        val packet = DatagramPacket(buffer, buffer.size)
                        socket?.receive(packet)
                        val payload = String(packet.data, 0, packet.length, Charsets.UTF_8)
                        val json = JSONObject(payload)
                        val nodeId = json.optString("node_id")
                        if (nodeId.isNotBlank()) {
                            peers[nodeId] = PeerEntry(nodeId, json.optString("endpoint"))
                            log("Discovered peer $nodeId at ${json.optString("endpoint")}")
                        }
                    } catch (_: Exception) {
                    }
                }
            } catch (error: Exception) {
                log("Peer discovery stopped: ${error.message}")
            } finally {
                socket?.close()
            }
        }.start()
    }

    fun stop() {
        running.set(false)
        socket?.close()
    }

    private fun broadcastAddress(): InetAddress = InetAddress.getByName("255.255.255.255")

    private fun localAddress(): String {
        return try {
            DatagramSocket().use { socket ->
                socket.connect(InetAddress.getByName("8.8.8.8"), 53)
                socket.localAddress.hostAddress
            }
        } catch (_: Exception) {
            "127.0.0.1"
        }
    }

    private fun log(message: String) {
        logFile.appendText("${System.currentTimeMillis()} - $message\n")
    }
}

private data class PeerEntry(val nodeId: String, val endpoint: String)
