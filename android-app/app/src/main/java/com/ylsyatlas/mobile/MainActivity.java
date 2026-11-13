package com.ylsyatlas.mobile;

import android.graphics.Color;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.util.Base64;
import android.net.Uri;
import android.os.Bundle;
import android.os.Message;
import android.os.Environment;
import android.provider.Settings;
import android.view.View;
import android.webkit.WebChromeClient;
import android.webkit.ValueCallback;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.Toast;
import java.io.OutputStream;
import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.core.graphics.Insets;
import androidx.core.content.FileProvider;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.util.concurrent.Executors;

public final class MainActivity extends ComponentActivity {
    private static final int THEME = Color.rgb(7, 15, 29);
    private WebView web;
    private ValueCallback<Uri[]> fileChooserCallback;
    private byte[] pendingFile;
    private String pendingFilename, pendingMime;
    private static final int REQUEST_OPEN_FILE = 4201, REQUEST_SAVE_FILE = 4202;
    private static final int REQUEST_UPDATE_PERMISSION = 4301, REQUEST_UPDATE_INSTALL = 4302;
    private static final String RELEASES_URL = "https://api.github.com/repos/dk-emita/ylsy_atlas/releases/latest";
    private static final String CURRENT_VERSION = "4.0.0";
    private UpdateInfo pendingUpdate;
    private File pendingUpdateApk;
    private AlertDialog updateProgressDialog;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        getWindow().setStatusBarColor(THEME);
        getWindow().setNavigationBarColor(THEME);
        getWindow().setNavigationBarDividerColor(THEME);
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            getWindow().setStatusBarContrastEnforced(false);
            getWindow().setNavigationBarContrastEnforced(false);
        }
        new WindowInsetsControllerCompat(getWindow(), getWindow().getDecorView()).setAppearanceLightStatusBars(false);
        new WindowInsetsControllerCompat(getWindow(), getWindow().getDecorView()).setAppearanceLightNavigationBars(false);
        AndroidBridge.init(this);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(THEME);
        ViewCompat.setOnApplyWindowInsetsListener(root, (view, windowInsets) -> {
            Insets safe = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
            return windowInsets;
        });
        web = new WebView(this);
        web.setBackgroundColor(THEME);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        ProgressBar progress = new ProgressBar(this);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        root.addView(progress, new FrameLayout.LayoutParams(-2, -2, android.view.Gravity.CENTER));
        setContentView(root);

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setSupportMultipleWindows(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(true);
        web.addJavascriptInterface(new AndroidFileBridge(), "AndroidAtlas");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String host = uri.getHost();
                if ("127.0.0.1".equals(host) || "localhost".equals(host)) return false;
                AndroidBridge.openUrl(uri.toString());
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileChooserCallback != null) fileChooserCallback.onReceiveValue(null);
                fileChooserCallback = callback;
                try { startActivityForResult(params.createIntent(), REQUEST_OPEN_FILE); return true; }
                catch (Exception error) { fileChooserCallback = null; callback.onReceiveValue(null); return false; }
            }
            @Override public boolean onCreateWindow(WebView source, boolean dialog, boolean userGesture, Message resultMessage) {
                WebView popup = new WebView(MainActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    private boolean routed;
                    @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                        if (routed) return true;
                        routed = true;
                        Uri uri = request.getUrl();
                        String host = uri.getHost();
                        // Android WebView has no built-in PDF viewer. Open local PDF and
                        // other target-blank links in the system browser, keeping Atlas alive.
                        AndroidBridge.openUrl(uri.toString());
                        view.post(view::destroy);
                        return true;
                    }
                });
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMessage.obj;
                transport.setWebView(popup);
                resultMessage.sendToTarget();
                return true;
            }
        });

        checkForUpdateThenStart(progress);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {
                web.evaluateJavascript("(()=>{const a=document.getElementById('account-root');if(a&&a.childElementCount){a.replaceChildren();return 'overlay'}const m=document.getElementById('modal-root');if(m&&m.childElementCount){m.replaceChildren();return 'overlay'}const q=document.getElementById('search-root');if(q&&q.childElementCount){q.replaceChildren();return 'overlay'}if(document.body.classList.contains('mobile-open')){document.body.classList.remove('mobile-open');return 'drawer'}if(history.length>1){history.back();return 'page'}return 'root'})()", value -> { if ("\"root\"".equals(value)) finish(); });
            }
        });
    }

    private void checkForUpdateThenStart(ProgressBar progress) {
        Executors.newSingleThreadExecutor().execute(() -> {
            UpdateInfo update = null;
            try { if (hasValidatedInternet()) update = fetchLatestUpdate(); }
            catch (Exception ignored) { /* GitHub unavailable: keep the current offline-capable app usable. */ }
            if (update != null) {
                UpdateInfo found = update;
                runOnUiThread(() -> showMandatoryUpdate(found, progress, null));
            } else startAtlas(progress);
        });
    }

    private void startAtlas(ProgressBar progress) {
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        Executors.newSingleThreadExecutor().execute(() -> {
            try {
                PyObject entry = Python.getInstance().getModule("mobile_entry");
                String url = entry.callAttr("start_server", this).toString();
                runOnUiThread(() -> { progress.setVisibility(View.GONE); web.loadUrl(url); });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    progress.setVisibility(View.GONE);
                    web.loadData("<meta name='viewport' content='width=device-width'><body style='font:16px sans-serif;background:#070f1d;color:white;padding:24px'>YLSY Atlas başlatılamadı. Uygulamayı yeniden açın.</body>", "text/html", "UTF-8");
                });
            }
        });
    }

    private boolean hasValidatedInternet() {
        ConnectivityManager manager = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null) return false;
        Network network = manager.getActiveNetwork();
        NetworkCapabilities caps = network == null ? null : manager.getNetworkCapabilities(network);
        return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private UpdateInfo fetchLatestUpdate() throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(RELEASES_URL).openConnection();
        connection.setRequestMethod("GET");
        connection.setConnectTimeout(3500);
        connection.setReadTimeout(3500);
        connection.setRequestProperty("Accept", "application/vnd.github+json");
        connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        connection.setRequestProperty("User-Agent", "YLSYAtlas-Android");
        try {
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) return null;
            StringBuilder body = new StringBuilder();
            try (BufferedInputStream input = new BufferedInputStream(connection.getInputStream())) {
                byte[] buffer = new byte[8192]; int count;
                while ((count = input.read(buffer)) != -1) body.append(new String(buffer, 0, count, java.nio.charset.StandardCharsets.UTF_8));
            }
            JSONObject release = new JSONObject(body.toString());
            String tag = release.optString("tag_name", "").trim();
            String current = getInstalledVersion();
            if (tag.isEmpty() || compareVersions(tag, current) <= 0) return null;
            String apkUrl = null;
            JSONArray assets = release.optJSONArray("assets");
            if (assets != null) for (int i = 0; i < assets.length(); i++) {
                JSONObject asset = assets.optJSONObject(i);
                if (asset == null) continue;
                String name = asset.optString("name", "").toLowerCase(Locale.ROOT);
                String url = asset.optString("browser_download_url", "");
                if (name.endsWith(".apk") && name.contains("android") && url.startsWith("https://github.com/")) { apkUrl = url; break; }
            }
            return new UpdateInfo(tag, apkUrl);
        } finally { connection.disconnect(); }
    }

    private String getInstalledVersion() {
        try {
            PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            return info.versionName == null ? CURRENT_VERSION : info.versionName;
        } catch (Exception ignored) { return CURRENT_VERSION; }
    }

    private int compareVersions(String left, String right) {
        int[] a = versionParts(left), b = versionParts(right);
        for (int i = 0; i < 3; i++) if (a[i] != b[i]) return Integer.compare(a[i], b[i]);
        return 0;
    }

    private int[] versionParts(String value) {
        int[] parts = new int[] {0, 0, 0};
        String[] pieces = value.replaceFirst("^[vV]", "").split("[.+-]", 4);
        try { for (int i = 0; i < Math.min(3, pieces.length); i++) parts[i] = Integer.parseInt(pieces[i].replaceAll("[^0-9].*$", "")); }
        catch (Exception ignored) { return new int[] {0, 0, 0}; }
        return parts;
    }

    private void showMandatoryUpdate(UpdateInfo update, ProgressBar progress, String error) {
        if (isFinishing()) return;
        pendingUpdate = update;
        progress.setVisibility(View.GONE);
        String message = error == null ? "Yeni sürüm (" + update.version + ") yayımlandı. Uygulamayı kullanmak için güncelleyin." : error;
        new AlertDialog.Builder(this)
                .setTitle("YLSY Atlas güncellemesi gerekli")
                .setMessage(message)
                .setCancelable(false)
                .setPositiveButton("Güncelle", (dialog, which) -> downloadUpdate(update, progress))
                .setNegativeButton("Çıkış", (dialog, which) -> finish())
                .show().setCanceledOnTouchOutside(false);
    }

    private void downloadUpdate(UpdateInfo update, ProgressBar progress) {
        if (update.apkUrl == null) {
            showMandatoryUpdate(update, progress, "Yeni sürüm var ancak GitHub sürümüne Android APK dosyası eklenmemiş. Uygulamayı kullanmak için APK yayımlanmalı.");
            return;
        }
        updateProgressDialog = new AlertDialog.Builder(this)
                .setTitle("Güncelleme indiriliyor")
                .setMessage(update.version + " sürümü hazırlanıyor…")
                .setCancelable(false)
                .setNegativeButton("Çıkış", (dialog, which) -> finish())
                .create();
        updateProgressDialog.show();
        updateProgressDialog.setCanceledOnTouchOutside(false);
        Executors.newSingleThreadExecutor().execute(() -> {
            try {
                HttpURLConnection connection = (HttpURLConnection) new URL(update.apkUrl).openConnection();
                connection.setConnectTimeout(12000); connection.setReadTimeout(30000); connection.setInstanceFollowRedirects(true);
                connection.setRequestProperty("User-Agent", "YLSYAtlas-Android");
                File directory = new File(getFilesDir(), "updates");
                if (!directory.exists() && !directory.mkdirs()) throw new java.io.IOException("Güncelleme klasörü oluşturulamadı.");
                File part = new File(directory, "ylsy-atlas-update.apk.part");
                File apk = new File(directory, "ylsy-atlas-update.apk");
                try {
                    if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) throw new java.io.IOException("GitHub güncelleme dosyasını indirmedi.");
                    try (BufferedInputStream input = new BufferedInputStream(connection.getInputStream()); FileOutputStream output = new FileOutputStream(part)) {
                        byte[] buffer = new byte[64 * 1024]; int count; long total = 0;
                        while ((count = input.read(buffer)) != -1) { total += count; if (total > 350L * 1024L * 1024L) throw new java.io.IOException("Güncelleme dosyası beklenenden büyük."); output.write(buffer, 0, count); }
                        output.getFD().sync();
                    }
                } finally { connection.disconnect(); }
                if (!part.isFile() || part.length() < 1024) throw new java.io.IOException("İndirilen APK dosyası geçersiz.");
                if (apk.exists() && !apk.delete()) throw new java.io.IOException("Önceki geçici güncelleme silinemedi.");
                if (!part.renameTo(apk)) throw new java.io.IOException("Güncelleme dosyası hazırlanamadı.");
                pendingUpdateApk = apk;
                runOnUiThread(() -> { if (updateProgressDialog != null) updateProgressDialog.dismiss(); launchUpdateInstaller(); });
            } catch (Exception failure) {
                runOnUiThread(() -> {
                    if (updateProgressDialog != null) updateProgressDialog.dismiss();
                    showMandatoryUpdate(update, progress, "Güncelleme indirilemedi. İnternet bağlantısını kontrol edip yeniden deneyin.");
                });
            }
        });
    }

    private void launchUpdateInstaller() {
        if (pendingUpdateApk == null) { showMandatoryUpdate(pendingUpdate, new ProgressBar(this), "Güncelleme dosyası bulunamadı. Yeniden deneyin."); return; }
        if (android.os.Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
            try {
                Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName()));
                startActivityForResult(settings, REQUEST_UPDATE_PERMISSION);
            } catch (Exception error) { showMandatoryUpdate(pendingUpdate, new ProgressBar(this), "Android ayarlarında bu uygulamaya güncelleme izni verin."); }
            return;
        }
        try {
            Uri content = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", pendingUpdateApk);
            Intent install = new Intent(Intent.ACTION_INSTALL_PACKAGE);
            install.setDataAndType(content, "application/vnd.android.package-archive");
            install.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(install, REQUEST_UPDATE_INSTALL);
        } catch (Exception error) { showMandatoryUpdate(pendingUpdate, new ProgressBar(this), "Android güncelleme ekranı açılamadı. Yeniden deneyin."); }
    }

    private static final class UpdateInfo {
        final String version, apkUrl;
        UpdateInfo(String version, String apkUrl) { this.version = version; this.apkUrl = apkUrl; }
    }

    private final class AndroidFileBridge {
        @JavascriptInterface public void saveFile(String name, String base64, String mime) {
            try {
                pendingFile = Base64.decode(base64, Base64.DEFAULT);
                pendingFilename = name == null ? "YLSY-Atlas-dosya" : name.replaceAll("[\\/:*?\"<>|]", "_");
                pendingMime = mime == null || mime.isEmpty() ? "application/octet-stream" : mime;
                runOnUiThread(() -> {
                    Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType(pendingMime);
                    intent.putExtra(Intent.EXTRA_TITLE, pendingFilename);
                    startActivityForResult(intent, REQUEST_SAVE_FILE);
                });
            } catch (Exception error) { runOnUiThread(() -> Toast.makeText(MainActivity.this, "Dosya dışa aktarılamadı", Toast.LENGTH_LONG).show()); }
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_OPEN_FILE && fileChooserCallback != null) {
            fileChooserCallback.onReceiveValue(resultCode == RESULT_OK && data != null ? WebChromeClient.FileChooserParams.parseResult(resultCode, data) : null);
            fileChooserCallback = null;
        } else if (requestCode == REQUEST_UPDATE_PERMISSION) {
            if (android.os.Build.VERSION.SDK_INT < 26 || getPackageManager().canRequestPackageInstalls()) launchUpdateInstaller();
            else showMandatoryUpdate(pendingUpdate, new ProgressBar(this), "Güncellemenin yüklenmesi için Android ayarlarından izin verin.");
        } else if (requestCode == REQUEST_UPDATE_INSTALL) {
            if (pendingUpdate != null && compareVersions(getInstalledVersion(), pendingUpdate.version) >= 0) {
                Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
                finish();
                if (launch != null) startActivity(launch);
            } else if (pendingUpdate != null) {
                showMandatoryUpdate(pendingUpdate, new ProgressBar(this), "Güncelleme tamamlanmadı. Uygulamayı kullanmak için güncellemeyi yükleyin.");
            }
        } else if (requestCode == REQUEST_SAVE_FILE) {
            try {
                if (resultCode == RESULT_OK && data != null && data.getData() != null && pendingFile != null) {
                    try (OutputStream out = getContentResolver().openOutputStream(data.getData())) { if (out != null) out.write(pendingFile); }
                    Toast.makeText(this, "Dosya kaydedildi", Toast.LENGTH_LONG).show();
                }
            } catch (Exception error) { Toast.makeText(this, "Dosya kaydedilemedi", Toast.LENGTH_LONG).show(); }
            finally { pendingFile = null; pendingFilename = null; pendingMime = null; }
        }
    }

    @Override public void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
