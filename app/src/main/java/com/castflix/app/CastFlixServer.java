package com.castflix.app;

import android.content.Context;
import android.util.Log;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * CastFlix HTTP server in pure Java. Mirrors the Python server.py API
 * so the same web UI (assets/index.html) works unchanged:
 *   GET /                  -> CastFlix web UI
 *   GET /api/status        -> {"pin_required": false}
 *   GET /api/library       -> {"movies": [...], "series": [...]}
 *   GET /stream?id=...     -> video file, with HTTP Range (seeking)
 *   GET /poster?id=...     -> poster.jpg / cover.jpg, if present
 *   GET /subtitles?id=...  -> .vtt directly, .srt converted to WebVTT
 *
 * No external libraries. Files are read from the folder the user
 * typed in MainActivity, recursively.
 */
public class CastFlixServer {

    private static final String[] VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"};
    private static final String[] POSTER_NAMES = {"poster.jpg", "poster.jpeg", "poster.png", "cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png"};

    private final Context context;
    private final File root;
    private final int port;
    private ServerSocket serverSocket;
    private ExecutorService pool;
    private volatile boolean running = false;

    // Library, built once at start.
    private final List<Map<String, Object>> movies = new ArrayList<Map<String, Object>>();
    private final List<Map<String, Object>> seriesList = new ArrayList<Map<String, Object>>();
    private final Map<String, File> pathById = new HashMap<String, File>();
    private final Map<String, File> posterById = new HashMap<String, File>();
    private final Map<String, File> vttById = new HashMap<String, File>();
    private final Map<String, File> srtById = new HashMap<String, File>();

    public CastFlixServer(Context context, String folderPath, int port) {
        this.context = context.getApplicationContext();
        this.root = new File(folderPath);
        this.port = port;
    }

    // ---------- IP address ----------

    public static String getLocalIp() {
        try {
            String fallback = "127.0.0.1";
            Enumeration<NetworkInterface> ifs = NetworkInterface.getNetworkInterfaces();
            while (ifs.hasMoreElements()) {
                NetworkInterface ni = ifs.nextElement();
                if (!ni.isUp() || ni.isLoopback()) continue;
                Enumeration<InetAddress> addrs = ni.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress a = addrs.nextElement();
                    if (a instanceof Inet4Address && !a.isLoopbackAddress()) {
                        String ip = a.getHostAddress();
                        if (ip == null) continue;
                        if (a.isSiteLocalAddress()) return ip;
                        if (fallback.equals("127.0.0.1")) fallback = ip;
                    }
                }
            }
            return fallback;
        } catch (Exception e) {
            return "127.0.0.1";
        }
    }

    // ---------- Start / stop ----------

    public void start() throws IOException {
        buildLibrary();
        serverSocket = new ServerSocket(port);
        pool = Executors.newFixedThreadPool(8);
        running = true;
        Thread acceptThread = new Thread(new Runnable() {
            @Override public void run() {
                while (running) {
                    try {
                        final Socket socket = serverSocket.accept();
                        pool.execute(new Runnable() {
                            @Override public void run() {
                                handle(socket);
                            }
                        });
                    } catch (IOException e) {
                        if (running) Log.e("CastFlix", "Accept failed", e);
                    }
                }
            }
        });
        acceptThread.start();
        Log.i("CastFlix", "Server on port " + port + ", " + movies.size() + " movies, " + seriesList.size() + " series");
    }

    public void stop() {
        running = false;
        try {
            if (serverSocket != null) serverSocket.close();
        } catch (IOException ignored) {
        }
        if (pool != null) pool.shutdownNow();
    }

    // ---------- Library scan ----------

    private static String sha12(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            byte[] d = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 6; i++) sb.append(String.format("%02x", d[i]));
            return sb.toString();
        } catch (Exception e) {
            return String.valueOf(Math.abs(s.hashCode()));
        }
    }

    private static final Pattern QUALITY = Pattern.compile(
            "\\b(2160p|1080p|720p|480p|4k|web-dl|webdl|bluray|blu-ray|hdrip|brrip|x264|x265|h\\.?264|h\\.?265|hevc|aac|ac3|dts|10bit|8bit|proper|repack|extended|remux)\\b",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern YEAR = Pattern.compile("\\b(19\\d\\d|20\\d\\d)\\b");
    private static final Pattern SEASON_EP = Pattern.compile("[Ss](\\d{1,2})[Ee](\\d{1,2})");
    private static final Pattern SEASON_FOLDER = Pattern.compile("season\\s*(\\d+)", Pattern.CASE_INSENSITIVE);

    private static String cleanTitle(String raw) {
        if (raw == null) return "";
        String t = QUALITY.matcher(raw).replaceAll(" ");
        t = t.replaceAll("[\\._\\-]+", " ");
        t = t.replaceAll("\\[.*?\\]|\\(.*?\\)", " ");
        t = t.replaceAll("\\s+", " ").trim();
        return t;
    }

    private static Integer extractYear(String s) {
        if (s == null) return null;
        Matcher m = YEAR.matcher(s);
        if (m.find()) {
            try { return Integer.parseInt(m.group(1)); } catch (Exception e) { return null; }
        }
        return null;
    }

    private static boolean isVideo(File f) {
        String n = f.getName().toLowerCase();
        for (String ext : VIDEO_EXTS) if (n.endsWith(ext)) return true;
        return false;
    }

    private static boolean isBrowserFriendly(String ext) {
        return ".mp4".equals(ext) || ".webm".equals(ext);
    }

    private static String extOf(File f) {
        String n = f.getName();
        int i = n.lastIndexOf('.');
        return i >= 0 ? n.substring(i).toLowerCase() : "";
    }

    private static String stemOf(File f) {
        String n = f.getName();
        int i = n.lastIndexOf('.');
        return i >= 0 ? n.substring(0, i) : n;
    }

    private void buildLibrary() {
        movies.clear();
        seriesList.clear();
        pathById.clear();
        posterById.clear();
        vttById.clear();
        srtById.clear();
        if (!root.isDirectory()) return;
        List<File> files = new ArrayList<File>();
        collect(root, files);
        Collections.sort(files, new Comparator<File>() {
            @Override public int compare(File a, File b) { return a.getAbsolutePath().compareTo(b.getAbsolutePath()); }
        });

        Map<String, Map<String, Object>> seriesMap = new HashMap<String, Map<String, Object>>();
        Map<String, List<Map<String, Object>>> episodesByShow = new HashMap<String, List<Map<String, Object>>>();

        for (File f : files) {
            String rel = root.toURI().relativize(f.toURI()).getPath();
            String parent = f.getParentFile() != null ? f.getParentFile().getAbsolutePath() : "";
            String parentRel = root.toURI().relativize(new File(parent).toURI()).getPath();
            String[] parts = parentRel.split("/");
            List<String> partList = new ArrayList<String>();
            for (String p : parts) if (p != null && !p.isEmpty() && !p.equals("/")) partList.add(p);
            String stem = stemOf(f);
            String ext = extOf(f);
            String id = sha12(rel);
            File poster = findPoster(f.getParentFile(), stem);
            File vtt = new File(f.getParentFile(), stem + ".vtt");
            File srt = new File(f.getParentFile(), stem + ".srt");
            pathById.put(id, f);
            if (poster != null) posterById.put(id, poster);
            if (vtt.exists()) vttById.put(id, vtt);
            if (srt.exists()) srtById.put(id, srt);

            Matcher se = SEASON_EP.matcher(stem);
            Integer seasonFolder = null;
            for (String p : partList) {
                Matcher sm = SEASON_FOLDER.matcher(p);
                if (sm.find()) { try { seasonFolder = Integer.parseInt(sm.group(1)); } catch (Exception ignored) {} break; }
            }
            if (se.find() || seasonFolder != null) {
                // se.find() above already matched, if any. Re-create for season/episode numbers.
                Matcher se2 = SEASON_EP.matcher(stem);
                int sNum, eNum;
                if (se2.find()) { sNum = Integer.parseInt(se2.group(1)); eNum = Integer.parseInt(se2.group(2)); }
                else { sNum = seasonFolder != null ? seasonFolder : 1; eNum = 0; }
                // Show name: parent of a Season folder, else prefix before SxxExx.
                String showRaw;
                Matcher se3 = SEASON_EP.matcher(stem);
                if (seasonFolder != null && partList.size() >= 2) showRaw = partList.get(partList.size() - 2);
                else if (se3.find()) showRaw = stem.substring(0, se3.start());
                else if (!partList.isEmpty()) showRaw = partList.get(0);
                else showRaw = stem;
                String showTitle = cleanTitle(showRaw);
                if (showTitle.isEmpty()) showTitle = "Unknown Series";
                String showId = sha12(showTitle.toLowerCase());
                if (!seriesMap.containsKey(showId)) {
                    Map<String, Object> entry = new HashMap<String, Object>();
                    entry.put("id", showId);
                    entry.put("title", showTitle);
                    Integer y = extractYear(showRaw);
                    if (y != null) entry.put("year", y);
                    entry.put("poster_url", poster != null ? "/poster?id=" + showId : null);
                    seriesMap.put(showId, entry);
                    episodesByShow.put(showId, new ArrayList<Map<String, Object>>());
                    if (poster != null) posterById.put(showId, poster);
                }
                Map<String, Object> ep = new HashMap<String, Object>();
                ep.put("id", id);
                ep.put("title", String.format("S%02dE%02d", sNum, eNum));
                ep.put("season", sNum);
                ep.put("episode", eNum);
                ep.put("file", f.getName());
                ep.put("size", f.length());
                ep.put("ext", ext);
                ep.put("browser_friendly", isBrowserFriendly(ext));
                ep.put("has_subtitles", vtt.exists() || srt.exists());
                episodesByShow.get(showId).add(ep);
                continue;
            }

            String movieRaw;
            if (!partList.isEmpty()) {
                String last = partList.get(partList.size() - 1).toLowerCase();
                if (!last.equals("movies") && !last.equals("movie") && !last.equals("series") && !last.equals("videos") && !last.equals("media") && !last.equals("downloads") && !last.equals("download")) {
                    movieRaw = partList.get(partList.size() - 1);
                } else {
                    movieRaw = stem;
                }
            } else {
                movieRaw = stem;
            }
            String title = cleanTitle(movieRaw);
            if (title.isEmpty()) title = cleanTitle(stem);
            if (title.isEmpty()) title = "Unknown";
            Map<String, Object> item = new HashMap<String, Object>();
            item.put("id", id);
            item.put("title", title);
            Integer y = extractYear(movieRaw);
            if (y == null) y = extractYear(stem);
            if (y != null) item.put("year", y);
            item.put("file", f.getName());
            item.put("size", f.length());
            item.put("ext", ext);
            item.put("browser_friendly", isBrowserFriendly(ext));
            item.put("has_subtitles", vtt.exists() || srt.exists());
            item.put("poster_url", poster != null ? "/poster?id=" + id : null);
            movies.add(item);
        }

        for (Map.Entry<String, Map<String, Object>> e : seriesMap.entrySet()) {
            List<Map<String, Object>> eps = episodesByShow.get(e.getKey());
            Collections.sort(eps, new Comparator<Map<String, Object>>() {
                @Override public int compare(Map<String, Object> a, Map<String, Object> b) {
                    int sa = (Integer) a.get("season"), sb = (Integer) b.get("season");
                    if (sa != sb) return sa - sb;
                    return (Integer) a.get("episode") - (Integer) b.get("episode");
                }
            });
            e.getValue().put("episodes", eps);
            seriesList.add(e.getValue());
        }
        Collections.sort(movies, new Comparator<Map<String, Object>>() {
            @Override public int compare(Map<String, Object> a, Map<String, Object> b) {
                return ((String) a.get("title")).compareToIgnoreCase((String) b.get("title"));
            }
        });
        Collections.sort(seriesList, new Comparator<Map<String, Object>>() {
            @Override public int compare(Map<String, Object> a, Map<String, Object> b) {
                return ((String) a.get("title")).compareToIgnoreCase((String) b.get("title"));
            }
        });
    }

    private static void collect(File dir, List<File> out) {
        File[] children = dir.listFiles();
        if (children == null) return;
        for (File c : children) {
            if (c.isDirectory()) collect(c, out);
            else if (isVideo(c)) out.add(c);
        }
    }

    private static File findPoster(File folder, String stem) {
        if (folder == null) return null;
        for (String name : POSTER_NAMES) {
            File p = new File(folder, name);
            if (p.exists()) return p;
        }
        for (String ext : new String[]{".jpg", ".jpeg", ".png"}) {
            File p = new File(folder, stem + ext);
            if (p.exists()) return p;
        }
        return null;
    }

    // ---------- JSON ----------

    private static String jsonEsc(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder();
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"') sb.append("\\\"");
            else if (c == '\\') sb.append("\\\\");
            else if (c == '\n') sb.append("\\n");
            else if (c == '\r') sb.append("\\r");
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        sb.append('"');
        return sb.toString();
    }

    private String libraryJson() {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"movies\":[");
        for (int i = 0; i < movies.size(); i++) {
            if (i > 0) sb.append(',');
            Map<String, Object> m = movies.get(i);
            sb.append("{\"id\":").append(jsonEsc((String) m.get("id")));
            sb.append(",\"title\":").append(jsonEsc((String) m.get("title")));
            if (m.get("year") != null) sb.append(",\"year\":").append(m.get("year"));
            else sb.append(",\"year\":null");
            sb.append(",\"file\":").append(jsonEsc((String) m.get("file")));
            sb.append(",\"size\":").append(m.get("size"));
            sb.append(",\"ext\":").append(jsonEsc((String) m.get("ext")));
            sb.append(",\"browser_friendly\":").append(m.get("browser_friendly"));
            sb.append(",\"has_subtitles\":").append(m.get("has_subtitles"));
            Object pu = m.get("poster_url");
            sb.append(",\"poster_url\":").append(pu == null ? "null" : jsonEsc((String) pu));
            sb.append('}');
        }
        sb.append("],\"series\":[");
        for (int i = 0; i < seriesList.size(); i++) {
            if (i > 0) sb.append(',');
            Map<String, Object> s = seriesList.get(i);
            sb.append("{\"id\":").append(jsonEsc((String) s.get("id")));
            sb.append(",\"title\":").append(jsonEsc((String) s.get("title")));
            if (s.get("year") != null) sb.append(",\"year\":").append(s.get("year"));
            else sb.append(",\"year\":null");
            Object pu = s.get("poster_url");
            sb.append(",\"poster_url\":").append(pu == null ? "null" : jsonEsc((String) pu));
            sb.append(",\"episodes\":[");
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> eps = (List<Map<String, Object>>) s.get("episodes");
            for (int j = 0; j < eps.size(); j++) {
                if (j > 0) sb.append(',');
                Map<String, Object> e = eps.get(j);
                sb.append("{\"id\":").append(jsonEsc((String) e.get("id")));
                sb.append(",\"title\":").append(jsonEsc((String) e.get("title")));
                sb.append(",\"season\":").append(e.get("season"));
                sb.append(",\"episode\":").append(e.get("episode"));
                sb.append(",\"file\":").append(jsonEsc((String) e.get("file")));
                sb.append(",\"size\":").append(e.get("size"));
                sb.append(",\"ext\":").append(jsonEsc((String) e.get("ext")));
                sb.append(",\"browser_friendly\":").append(e.get("browser_friendly"));
                sb.append(",\"has_subtitles\":").append(e.get("has_subtitles"));
                sb.append('}');
            }
            sb.append("]}");
        }
        sb.append("]}");
        return sb.toString();
    }

    // ---------- HTTP ----------

    private void handle(Socket socket) {
        try {
            BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
            OutputStream out = socket.getOutputStream();
            String requestLine = in.readLine();
            if (requestLine == null || requestLine.isEmpty()) { socket.close(); return; }
            String[] parts = requestLine.split(" ");
            if (parts.length < 2) { socket.close(); return; }
            String method = parts[0];
            String fullPath = parts[1];
            String rangeHeader = null;
            String line;
            while ((line = in.readLine()) != null && !line.isEmpty()) {
                if (line.toLowerCase().startsWith("range:")) rangeHeader = line.substring(6).trim();
            }
            String path = fullPath;
            String query = "";
            int qi = fullPath.indexOf('?');
            if (qi >= 0) { path = fullPath.substring(0, qi); query = fullPath.substring(qi + 1); }
            Map<String, String> q = parseQuery(query);
            String id = q.get("id");

            if (path.equals("/") || path.equals("/index.html")) {
                byte[] data = readAsset("index.html");
                sendHeaders(out, 200, "text/html; charset=utf-8", data.length, null);
                if (!method.equals("HEAD")) out.write(data);
            } else if (path.equals("/api/status")) {
                byte[] data = "{\"pin_required\": false}".getBytes(StandardCharsets.UTF_8);
                sendHeaders(out, 200, "application/json", data.length, null);
                if (!method.equals("HEAD")) out.write(data);
            } else if (path.equals("/api/library")) {
                byte[] data = libraryJson().getBytes(StandardCharsets.UTF_8);
                sendHeaders(out, 200, "application/json", data.length, null);
                if (!method.equals("HEAD")) out.write(data);
            } else if (path.equals("/stream") && id != null && pathById.containsKey(id)) {
                serveFileRange(out, method, pathById.get(id), mimeFor(pathById.get(id)), rangeHeader);
            } else if (path.equals("/poster") && id != null && posterById.containsKey(id)) {
                serveFileRange(out, method, posterById.get(id), mimeFor(posterById.get(id)), rangeHeader);
            } else if (path.equals("/subtitles") && id != null) {
                if (vttById.containsKey(id)) {
                    serveFileRange(out, method, vttById.get(id), "text/vtt", rangeHeader);
                } else if (srtById.containsKey(id)) {
                    byte[] data = srtToVtt(srtById.get(id)).getBytes(StandardCharsets.UTF_8);
                    sendHeaders(out, 200, "text/vtt", data.length, null);
                    if (!method.equals("HEAD")) out.write(data);
                } else {
                    sendHeaders(out, 404, "text/plain", 0, null);
                }
            } else {
                sendHeaders(out, 404, "text/plain", 0, null);
            }
            out.flush();
            socket.close();
        } catch (Exception e) {
            Log.e("CastFlix", "Handle failed", e);
            try { socket.close(); } catch (IOException ignored) {}
        }
    }

    private static Map<String, String> parseQuery(String q) {
        Map<String, String> m = new HashMap<String, String>();
        if (q == null || q.isEmpty()) return m;
        for (String pair : q.split("&")) {
            int i = pair.indexOf('=');
            try {
                if (i >= 0) m.put(URLDecoder.decode(pair.substring(0, i), "UTF-8"), URLDecoder.decode(pair.substring(i + 1), "UTF-8"));
                else m.put(URLDecoder.decode(pair, "UTF-8"), "");
            } catch (Exception ignored) {}
        }
        return m;
    }

    private byte[] readAsset(String name) throws IOException {
        InputStream in = context.getAssets().open(name);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) >= 0) bos.write(buf, 0, n);
        in.close();
        return bos.toByteArray();
    }

    private static String mimeFor(File f) {
        String n = f.getName().toLowerCase();
        if (n.endsWith(".mp4")) return "video/mp4";
        if (n.endsWith(".webm")) return "video/webm";
        if (n.endsWith(".mkv")) return "video/x-matroska";
        if (n.endsWith(".mov")) return "video/quicktime";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".vtt")) return "text/vtt";
        return "application/octet-stream";
    }

    private static String srtToVtt(File srt) throws IOException {
        FileInputStream in = new FileInputStream(srt);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) >= 0) bos.write(buf, 0, n);
        in.close();
        String text = new String(bos.toByteArray(), StandardCharsets.UTF_8);
        text = text.replaceAll("(\\d{2}:\\d{2}:\\d{2}),(\\d{3})", "$1.$2");
        if (text.startsWith("\uFEFF")) text = text.substring(1);
        return "WEBVTT\n\n" + text;
    }

    private void sendHeaders(OutputStream out, int status, String contentType, long length, String contentRange) throws IOException {
        String statusText = status == 200 ? "OK" : status == 206 ? "Partial Content" : "Not Found";
        StringBuilder sb = new StringBuilder();
        sb.append("HTTP/1.1 ").append(status).append(' ').append(statusText).append("\r\n");
        sb.append("Content-Type: ").append(contentType).append("\r\n");
        sb.append("Accept-Ranges: bytes\r\n");
        sb.append("Content-Length: ").append(length).append("\r\n");
        if (contentRange != null) sb.append("Content-Range: ").append(contentRange).append("\r\n");
        sb.append("Connection: close\r\n\r\n");
        out.write(sb.toString().getBytes(StandardCharsets.UTF_8));
    }

    private void serveFileRange(OutputStream out, String method, File file, String contentType, String rangeHeader) throws IOException {
        long size = file.length();
        long start = 0, end = size - 1;
        int status = 200;
        String contentRange = null;
        if (rangeHeader != null) {
            Matcher m = Pattern.compile("bytes=(\\d*)-(\\d*)").matcher(rangeHeader.trim());
            if (m.find()) {
                if (m.group(1) != null && !m.group(1).isEmpty()) start = Long.parseLong(m.group(1));
                if (m.group(2) != null && !m.group(2).isEmpty()) end = Long.parseLong(m.group(2));
                if (end >= size) end = size - 1;
                if (start <= end) { status = 206; contentRange = "bytes " + start + "-" + end + "/" + size; }
            }
        }
        long length = end - start + 1;
        sendHeaders(out, status, contentType, length, contentRange);
        if (method.equals("HEAD")) return;
        FileInputStream in = new FileInputStream(file);
        long skipped = 0;
        while (skipped < start) {
            long s = in.skip(start - skipped);
            if (s <= 0) break;
            skipped += s;
        }
        byte[] buf = new byte[8192];
        long remaining = length;
        while (remaining > 0) {
            int toRead = (int) Math.min(buf.length, remaining);
            int read = in.read(buf, 0, toRead);
            if (read < 0) break;
            out.write(buf, 0, read);
            remaining -= read;
        }
        in.close();
    }
}
