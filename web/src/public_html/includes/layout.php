<?php
// EMB Pros: the header every page shares (the logo, the tools as tabs, the open one in orange).

if (!defined('EMB_PROS')) {
    define('EMB_PROS', true);
}

const EMB_NAV = [
    '/'        => 'Logo Vectorizer',
    '/pantone' => 'Pantone Match',
    '/thread'  => 'Thread Match',
    '/patch'   => 'Patch Mockup',
    '/gang'    => 'Gang Sheet Maker',
    '/cap'     => 'DST Maker',
];

// a script's or stylesheet's address with its version (when the file last changed), so a browser
// fetches it again as soon as it is updated, and keeps it while it is not
function emb_v(string $path): string
{
    $file = dirname(__DIR__) . $path;
    return htmlspecialchars($path . '?v=' . (is_file($file) ? filemtime($file) : 0));
}

function emb_header(string $current): void
{
    echo '<header class="top">' . "\n";
    echo '  <a class="brand" href="/" title="EMB Pros"><img src="/static/emb-pros-logo.svg" alt="EMB Pros" width="214" height="47"></a>' . "\n";
    // on a phone the tabs fold into a menu button (style.css)
    echo '  <input type="checkbox" id="navOpen" class="nav-check" hidden>' . "\n";
    echo '  <label class="nav-toggle" for="navOpen" aria-label="Menu" title="Menu"><span></span></label>' . "\n";
    echo '  <nav class="nav" aria-label="Tools">' . "\n";
    foreach (EMB_NAV as $href => $label) {
        $on = $href === $current ? ' aria-current="page"' : '';
        echo '    <a href="' . htmlspecialchars($href) . '"' . $on . '>' . htmlspecialchars($label) . "</a>\n";
    }
    echo "  </nav>\n</header>";
}
