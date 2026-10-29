<?php
// EMB Pros: every /api/... request of the pages, passed to the engine as it is and its answer
// passed back as it comes (uploads, JSON, and files: DST, PDF, PNG, EPS, TIFF...).
// .htaccess sends /api/<path> here as api.php?__path=<path>.

require __DIR__ . '/config.php';

// a warning printed into a file would break it: logged only
ini_set('display_errors', '0');

@set_time_limit(300);
ignore_user_abort(false);

function fail(int $code, string $message): void
{
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode(['error' => $message]);
    exit;
}

$path = $_GET['__path'] ?? '';
if (!preg_match('#^[A-Za-z0-9/_-]{1,80}$#', $path) || str_contains($path, '..')) {
    fail(404, 'Not found.');
}
if (!function_exists('curl_init')) {
    fail(500, 'This server\'s PHP has no cURL extension: turn it on (PHP settings, "curl").');
}
$query = $_GET;
unset($query['__path']);
$url = rtrim(EMB_ENGINE_URL, '/') . '/api/' . $path . ($query ? '?' . http_build_query($query) : '');

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$type = $_SERVER['CONTENT_TYPE'] ?? '';
$headers = ['Expect:'];
if (EMB_ENGINE_KEY !== '') {
    $headers[] = 'X-EMB-Key: ' . EMB_ENGINE_KEY;
}

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_CUSTOMREQUEST  => $method,
    CURLOPT_CONNECTTIMEOUT => 10,
    CURLOPT_TIMEOUT        => 290,
    CURLOPT_FOLLOWLOCATION => false,
]);

if ($method === 'POST') {
    if (stripos($type, 'multipart/form-data') === 0) {
        // an upload: PHP has already read it; sent on as the same form, files included
        if (empty($_FILES) && empty($_POST) && (int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 0) {
            fail(413, 'The file is larger than this server accepts (upload_max_filesize / post_max_size in .user.ini).');
        }
        $form = $_POST;
        foreach ($_FILES as $field => $f) {
            if (is_array($f['tmp_name'])) {
                foreach ($f['tmp_name'] as $i => $tmp) {
                    if ($f['error'][$i] !== UPLOAD_ERR_OK) {
                        fail(400, 'The upload failed (code ' . $f['error'][$i] . ').');
                    }
                    $form["{$field}[{$i}]"] = new CURLFile($tmp, $f['type'][$i] ?: 'application/octet-stream', $f['name'][$i]);
                }
            } else {
                if ($f['error'] !== UPLOAD_ERR_OK) {
                    fail($f['error'] === UPLOAD_ERR_INI_SIZE ? 413 : 400,
                        $f['error'] === UPLOAD_ERR_INI_SIZE ? 'The file is larger than this server accepts.' : 'The upload failed (code ' . $f['error'] . ').');
                }
                $form[$field] = new CURLFile($f['tmp_name'], $f['type'] ?: 'application/octet-stream', $f['name']);
            }
        }
        curl_setopt($ch, CURLOPT_POSTFIELDS, $form);
    } else {
        $headers[] = 'Content-Type: ' . ($type ?: 'application/json');
        curl_setopt($ch, CURLOPT_POSTFIELDS, file_get_contents('php://input'));
    }
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

// the engine's answer: its status and the headers that matter, then the body as it arrives
$pass = ['content-type', 'content-disposition', 'cache-control'];
curl_setopt($ch, CURLOPT_HEADERFUNCTION, function ($ch, $line) use ($pass) {
    if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m)) {
        http_response_code((int) $m[1]);
    } elseif (strpos($line, ':') !== false) {
        [$name, $value] = array_map('trim', explode(':', $line, 2));
        if (in_array(strtolower($name), $pass, true)) {
            header($name . ': ' . $value);
        }
    }
    return strlen($line);
});
while (ob_get_level() > 0) {
    ob_end_clean();
}
header('X-Accel-Buffering: no');
curl_setopt($ch, CURLOPT_WRITEFUNCTION, function ($ch, $data) {
    echo $data;
    flush();
    return strlen($data);
});

$ok = curl_exec($ch);
if ($ok === false) {
    $err = curl_error($ch);
    if (!headers_sent()) {
        fail(502, 'The EMB Pros engine is not reachable (' . $err . '). Check EMB_ENGINE_URL in config.php and that the engine is running.');
    }
}
if (PHP_VERSION_ID < 80000) {
    curl_close($ch);            // needed before PHP 8 only (deprecated since 8.5)
}
