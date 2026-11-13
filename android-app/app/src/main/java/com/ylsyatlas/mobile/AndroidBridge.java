package com.ylsyatlas.mobile;

import android.content.Intent;
import android.content.ActivityNotFoundException;
import android.os.Build;
import android.net.Uri;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class AndroidBridge {
    private static MainActivity activity;
    private AndroidBridge() {}
    public static void init(MainActivity value) { activity = value; }
    public static void startOAuthNetworkSession() {
        MainActivity target = activity;
        if (target == null) throw new IllegalStateException("Uygulama ekranı hazır değil.");
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<RuntimeException> failure = new AtomicReference<>();
        target.runOnUiThread(() -> {
            try {
                Intent intent = new Intent(target, OAuthNetworkService.class);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) target.startForegroundService(intent);
                else target.startService(intent);
            } catch (RuntimeException error) { failure.set(error); }
            finally { completed.countDown(); }
        });
        try {
            if (!completed.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("Google bağlantısı hazırlanırken zaman aşımına uğradı.");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Google bağlantısı kesildi.", interrupted);
        }
        if (failure.get() != null) throw new IllegalStateException("Google bağlantısı hazırlanamadı.", failure.get());
    }
    public static void stopOAuthNetworkSession() {
        MainActivity target = activity;
        if (target == null) return;
        target.runOnUiThread(() -> target.stopService(new Intent(target, OAuthNetworkService.class)));
    }
    public static void openUrl(String address) {
        MainActivity target = activity;
        if (target == null) throw new IllegalStateException("Uygulama ekranı hazır değil.");
        String value = address == null ? "" : address.trim();
        Uri uri = Uri.parse(value);
        String scheme = uri.getScheme();
        if (value.isEmpty() || !("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme))) {
            throw new IllegalArgumentException("Tarayıcıya açılacak güvenli bağlantı geçersiz.");
        }
        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
        intent.addCategory(Intent.CATEGORY_BROWSABLE);
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<RuntimeException> failure = new AtomicReference<>();
        target.runOnUiThread(() -> {
            try {
                target.startActivity(intent);
            } catch (ActivityNotFoundException missingBrowser) {
                try {
                    Intent chooser = Intent.createChooser(intent, "Bağlantıyı aç");
                    target.startActivity(chooser);
                } catch (RuntimeException error) {
                    failure.set(error);
                }
            } catch (RuntimeException error) {
                failure.set(error);
            } finally {
                completed.countDown();
            }
        });
        try {
            if (!completed.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("Tarayıcı açılışı zaman aşımına uğradı.");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Tarayıcı açılışı kesildi.", interrupted);
        }
        if (failure.get() != null) throw new IllegalStateException("Android tarayıcısı açılamadı.", failure.get());
    }
}
