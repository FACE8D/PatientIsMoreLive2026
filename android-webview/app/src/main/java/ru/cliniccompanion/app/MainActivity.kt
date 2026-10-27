package ru.cliniccompanion.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.SafeBrowsingResponse
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.net.http.SslError
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private val prefs by lazy { getSharedPreferences("clinic_companion", Context.MODE_PRIVATE) }
    private val requestNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        createNotificationChannel()
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        webView = WebView(this)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.allowFileAccess = false
        webView.settings.allowContentAccess = false
        webView.settings.javaScriptCanOpenWindowsAutomatically = false
        webView.settings.setSupportMultipleWindows(false)
        webView.settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        webView.settings.safeBrowsingEnabled = true
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
        webView.addJavascriptInterface(PushTokenBridge(this), "ClinicBridge")
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url ?: return true
                val base = android.net.Uri.parse(BuildConfig.WEBVIEW_BASE_URL)
                // Keep patient data inside the configured origin. External reference links are opened by the browser.
                if (url.host == base.host && url.scheme == base.scheme) return false
                startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, url))
                return true
            }
            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                handler?.cancel() // Never bypass certificate errors for clinical data.
            }
            override fun onSafeBrowsingHit(view: WebView?, request: WebResourceRequest?, threatType: Int, callback: SafeBrowsingResponse?) {
                callback?.backToSafety(true)
            }
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                view?.evaluateJavascript("(()=>{try{const t=window.ClinicBridge?.consumePushToken?.();if(t)window.dispatchEvent(new CustomEvent('nativepushregistered',{detail:t}));}catch(e){}})()", null)
            }
        }
        setContentView(webView)
        webView.loadUrl(BuildConfig.WEBVIEW_BASE_URL)
    }

    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel("clinic_alerts", "Контур — уведомления", NotificationManager.IMPORTANCE_HIGH)
            channel.description = "Сигналы и сообщения приложения. Это не гарантированный экстренный канал."
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    class PushTokenBridge(context: Context) {
        private val prefs = context.getSharedPreferences("clinic_companion", Context.MODE_PRIVATE)
        @JavascriptInterface fun consumePushToken(): String {
            val token = prefs.getString("fcm_token", "") ?: ""
            if (token.isNotBlank()) prefs.edit().remove("fcm_token").apply()
            return token
        }
    }
}
