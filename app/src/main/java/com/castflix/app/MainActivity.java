package com.castflix.app;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.List;

/**
 * CastFlix Android: start sharing, show the TV address, stop sharing.
 * The actual HTTP server lives in CastFlixServer and runs in
 * SharingService, so it keeps running while you watch on the TV.
 */
public class MainActivity extends Activity {

    private EditText folderInput;
    private EditText portInput;
    private TextView statusText;
    private TextView urlText;
    private Button startButton;
    private Button stopButton;
    private String currentUrl = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        folderInput = findViewById(R.id.folderInput);
        portInput = findViewById(R.id.portInput);
        statusText = findViewById(R.id.statusText);
        urlText = findViewById(R.id.urlText);
        startButton = findViewById(R.id.startButton);
        stopButton = findViewById(R.id.stopButton);
        Button copyButton = findViewById(R.id.copyButton);
        Button openButton = findViewById(R.id.openButton);

        requestStoragePermissions();

        startButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { startSharing(); }
        });
        stopButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { stopSharing(); }
        });
        copyButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                if (currentUrl == null) {
                    Toast.makeText(MainActivity.this, "Start sharing first", Toast.LENGTH_SHORT).show();
                    return;
                }
                ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                cm.setPrimaryClip(ClipData.newPlainText("CastFlix", currentUrl));
                Toast.makeText(MainActivity.this, "Copied: " + currentUrl, Toast.LENGTH_SHORT).show();
            }
        });
        openButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                String url = currentUrl;
                if (url == null) {
                    Toast.makeText(MainActivity.this, "Start sharing first", Toast.LENGTH_SHORT).show();
                    return;
                }
                // Test on this phone itself; the TV uses the LAN address.
                String testUrl = url.replace(CastFlixServer.getLocalIp(), "127.0.0.1");
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(testUrl)));
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        // If the foreground service is already running (app was reopened),
        // show its address again instead of "Not sharing yet".
        if (SharingService.running && SharingService.currentUrl != null) {
            currentUrl = SharingService.currentUrl;
            statusText.setText("Sharing: " + SharingService.currentFolder);
            urlText.setText(currentUrl);
            startButton.setEnabled(false);
            stopButton.setEnabled(true);
        }
    }

    private void requestStoragePermissions() {
        List<String> needed = new ArrayList<String>();
        if (Build.VERSION.SDK_INT >= 33) {
            needed.add(Manifest.permission.READ_MEDIA_VIDEO);
            needed.add(Manifest.permission.POST_NOTIFICATIONS);
        } else {
            needed.add(Manifest.permission.READ_EXTERNAL_STORAGE);
        }
        List<String> missing = new ArrayList<String>();
        for (String p : needed) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) missing.add(p);
        }
        if (!missing.isEmpty()) {
            requestPermissions(missing.toArray(new String[0]), 1001);
        }
    }

    private void startSharing() {
        String folder = folderInput.getText().toString().trim();
        if (folder.isEmpty()) folder = "/storage/emulated/0/Movies";
        int port = 8000;
        try {
            port = Integer.parseInt(portInput.getText().toString().trim());
        } catch (Exception e) {
            port = 8000;
            portInput.setText("8000");
        }
        String ip = CastFlixServer.getLocalIp();
        currentUrl = "http://" + ip + ":" + port;

        Intent intent = new Intent(this, SharingService.class);
        intent.setAction(SharingService.ACTION_START);
        intent.putExtra("folder", folder);
        intent.putExtra("port", port);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        statusText.setText("Sharing: " + folder);
        urlText.setText(currentUrl);
        startButton.setEnabled(false);
        stopButton.setEnabled(true);
        Toast.makeText(this, "Open on your TV: " + currentUrl, Toast.LENGTH_LONG).show();
    }

    private void stopSharing() {
        Intent intent = new Intent(this, SharingService.class);
        intent.setAction(SharingService.ACTION_STOP);
        startService(intent);
        currentUrl = null;
        statusText.setText("Not sharing yet.");
        urlText.setText("—");
        startButton.setEnabled(true);
        stopButton.setEnabled(false);
    }
}
