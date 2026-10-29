<?php
// EMB Pros: where the engine (the engine/ folder, running as a Python app) answers.
// Set the engine's address after setting it up (see DEPLOY.md); the key needs nothing.

// The engine's address. Same server, cPanel "Setup Python App": the app's URL, for example
// 'https://your-domain.com/engine'. A VPS: 'http://127.0.0.1:8765'. No slash at the end.
const EMB_ENGINE_URL = 'http://127.0.0.1:8765';

// A secret shared with the engine (its EMB_ENGINE_KEY), so only this site can use it: any long
// random text, the same on both sides. Left empty here, it is read from the file .emb-pros-key in
// the account's home folder (above public_html), which the engine reads too; no file: no key.
$embKey = '';
if ($embKey === '') {
    $home = function_exists('posix_getpwuid') && function_exists('posix_geteuid') ? (posix_getpwuid(posix_geteuid())['dir'] ?? '') : '';
    foreach (array_unique(array_filter([$home, getenv('HOME') ?: '', dirname(__DIR__)])) as $dir) {
        if (is_readable($dir . '/.emb-pros-key')) { $embKey = trim((string) file_get_contents($dir . '/.emb-pros-key')); break; }
    }
}
define('EMB_ENGINE_KEY', $embKey);
unset($embKey, $home, $dir);
