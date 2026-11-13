package com.ylsyatlas.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** OAuth credentials are encrypted with a non-exportable Android Keystore AES key. */
public final class AndroidSecretStore {
    private static final String ALIAS = "ylsy-atlas-drive-oauth-v1";
    private final SharedPreferences prefs;
    public AndroidSecretStore(Context context) { prefs = context.getSharedPreferences("oauth-vault", Context.MODE_PRIVATE); }
    private SecretKey key(boolean create) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(ALIAS)) return ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null)).getSecretKey();
        if (!create) return null;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).build());
        return generator.generateKey();
    }
    private static String text(Object value) { return value == null ? "" : String.valueOf(value); }
    public String getPassword(Object service, Object account) {
        try {
            String encoded = prefs.getString(text(service) + ":" + text(account), null); if (encoded == null) return null;
            ByteBuffer buffer = ByteBuffer.wrap(Base64.decode(encoded, Base64.NO_WRAP)); int size = buffer.getInt();
            byte[] iv = new byte[size]; buffer.get(iv); byte[] cipherText = new byte[buffer.remaining()]; buffer.get(cipherText);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(cipherText), StandardCharsets.UTF_8);
        } catch (Exception error) { return null; }
    }
    public void setPassword(Object service, Object account, Object value) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key(true));
            byte[] iv = cipher.getIV(); byte[] encrypted = cipher.doFinal(text(value).getBytes(StandardCharsets.UTF_8));
            ByteBuffer buffer = ByteBuffer.allocate(4 + iv.length + encrypted.length); buffer.putInt(iv.length).put(iv).put(encrypted);
            prefs.edit().putString(text(service) + ":" + text(account), Base64.encodeToString(buffer.array(), Base64.NO_WRAP)).apply();
        } catch (Exception error) { throw new IllegalStateException("Google hesabı güvenli depolanamadı", error); }
    }
    public void deletePassword(Object service, Object account) { prefs.edit().remove(text(service) + ":" + text(account)).apply(); }
}
