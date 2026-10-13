<?php
// Extract the username from the URL pattern
$usr = "sgiappic"; // Since the username is static, we can hardcode it

// Define the base path based on the username
$base_path = "/web/$usr/public_html/";

// Get the current directory from the REQUEST_URI
$pwd = preg_replace("|^/~$usr/|", "", $_SERVER["REQUEST_URI"]);

// Construct the full path
$full_path = $base_path . $pwd;

// Shortened path version for display
$pwdshort = preg_replace("|(.*www/)|", "$usr/", $full_path);

// Try to change the directory to the constructed path
if (!chdir($full_path)) {
    // If changing directory fails, construct an error message
    $msg = "Could not find " . $_SERVER["REQUEST_URI"] . "...";
    $msg .= " Could not find $full_path...";
    print_r($_SERVER); // Output server information for debugging
    echo $msg; // Display the error message
    throw new Exception($msg); // Throw an exception with the error message
}
?>

<html>
<head>
<title><?php echo getcwd(); ?></title>
<style type='text/css'>
  body {
    font-family: "Candara", sans-serif;
    font-size: 9pt;
    line-height: 10.5pt;
  }
  div.pic h3 {
    font-size: 9pt;
    margin: 0.5em 1em 0.2em 1em;
  }
  div.pic p {
    font-size: 11pt;
    margin: 0.2em 1em 0.1em 1em;
  }
  div.pic {
    display: block;
    float: left;
    background-color: white;
    border: 1px solid #ccc;
    padding: 2px;
    text-align: center;
    margin: 2px 10px 10px 2px;
    -moz-box-shadow: 6px 4px 4px rgb(80,80,90);    /* Firefox 3.5 */
    -webkit-box-shadow: 6px 4px 4px rgb(80,80,90); /* Chrome, Safari */
    box-shadow: 6px 4px 4px rgb(80,80,90);         /* New browsers */
    width: 320px;
    min-height: 330px;
    max-height: 360px;
  }
  h1 { color: rgb(40,40,80); }
  h2 { padding-top: 5pt; }
  h2 a { color: rgb(20,20,100); }
  h3 a { color: rgb(40,40,120); }
  a { text-decoration: none; color: rgb(50,50,150); }
  a:hover { text-decoration: underline; color: rgb(80,80,250); }
  div.dirlinks h2 { padding-top: 0pt; margin-bottom: 4pt; margin-left: -15pt; color: rgb(20,20,80); }
  div.dirlinks { margin: 0 15pt; }
  div.dirlinks a {
    font-size: 11pt; font-weight: bold;
    padding: 0 0.5em;
  }
  pre {
    font-family: monospace;
    max-width:1000px;
    white-space: pre-wrap;     /* css-3 */
    white-space: -moz-pre-wrap !important; /* Mozilla */
    white-space: -pre-wrap;    /* Opera 4-6 */
    white-space: -o-pre-wrap;  /* Opera 7 */
    word-wrap:   break-word;   /* Internet Explorer 5.5+ */
  }
</style>
</head>
<body>
<h1><?php echo $pwd;?></h1>
<!-- <h1><?php echo getcwd();?></h1> -->
<?php
$has_subs = false;
foreach (glob("*") as $filename) {
    if (is_dir($filename)) {
        $has_subs = true;
        break;
    }
}
if ($has_subs) {
    echo "<div class=\"dirlinks\">\n";
    echo "<h2>Directories</h2>\n";
    echo "<a href=\"../\">[parent]</a> ";
    foreach (glob("*") as $filename) {
        if (is_dir($filename)) {
            echo " <a href=\"$filename\">[$filename]</a>";
        }
    }
    echo "</div>";
} else {
    echo "<div class=\"dirlinks\">\n";
    echo "<h2><a href=\"../\">[parent]</a></h2>";
    echo "</div>";
}

foreach (array("00_README.txt", "README.txt", "readme.txt") as $readme) {
    if (file_exists($readme)) {
        $readmeblock = file_get_contents($readme);
        $readmeblock = preg_replace("|\[\[((?:(?!\]\])[^\|])*)\|([^\|\]]*)\]\]|", "<a href=\"$1\">$2</a>", $readmeblock);
        $readmeblock = preg_replace("|\[\[([^\|\]]*)\]\]|", "<a href=\"$1\">$1</a>", $readmeblock);
        echo "<pre class='readme'>\n"; echo $readmeblock; echo "</pre>";
    }
}
?>

<h2><a name="plots">Plots</a></h2>
<p>
<form>
    Filter: <input type="text" name="match" size="30" value="<?php echo isset($_GET['match']) ? htmlspecialchars($_GET['match']) : ''; ?>" />
    <input type="Submit" value="Go" />
    <input type="checkbox" name="regexp" <?php echo isset($_GET['regexp']) && $_GET['regexp'] ? "checked=\"checked\"" : ""; ?> >RegExp</input>
</form>
</p>
<div>
<?php

function matches($filename, $keywords, $regex) { // match filename to filter
    if (!empty($keywords)) {
        foreach ($keywords as $keyword) {
            if ($regex) {
                if (!preg_match('/.*' . preg_quote($keyword, '/') . '.*/', $filename)) return false;
            } else {
                if (!fnmatch('*' . $keyword . '*', $filename)) return false;
            }
        }
    }
    return true;
}

function is_animated($filename) { // check if gif is animated
    if (!($fh = @fopen($filename, 'rb'))) return false;
    $count = 0;
    while (!feof($fh) && $count < 2) {
        $chunk = fread($fh, 1024 * 100); // read 100kb at a time
        $count += preg_match_all('#\x00\x21\xF9\x04.{4}\x00(\x2C|\x21)#s', $chunk, $matches);
    }
    fclose($fh);
    return $count > 1;
}

$displayed = array();
if (isset($_GET['noplots']) && $_GET['noplots']) {
    echo "Plots will not be displayed.\n";
} else {
    // Get images to be displayed
    $disp_filenames = array(); // images to be displayed
    $png_filenames = glob("*.png");
    $keywords = isset($_GET['match']) ? explode(" ", $_GET['match']) : array();
    $regex = isset($_GET['regexp']) && $_GET['regexp'];

    foreach (glob("*.gif") as $filename) { // get animated GIFs
        if (!matches($filename, $keywords, $regex)) continue;
        $png_filename = preg_replace("~\.gif$~", '.png', $filename);
        if (is_animated($filename)) {
            if (in_array($png_filename, $png_filenames)) // remove PNG
                $png_filenames = array_diff($png_filenames, array($png_filename));
        } else if (in_array($png_filename, $png_filenames)) { // give preference to PNG
            continue;
        }
        array_push($disp_filenames, $filename);
    }
    foreach ($png_filenames as $filename) { // get PNGs
        if (!matches($filename, $keywords, $regex)) continue;
        array_push($disp_filenames, $filename);
    }
    foreach (glob("*.jpg") as $filename) { // get JPGs
        if (!matches($filename, $keywords, $regex)) continue;
        $png_filename = preg_replace("~\.jpg$~", '.png', $filename);
        $gif_filename = preg_replace("~\.jpg$~", '.gif', $filename);
        if (!in_array($png_filename, $disp_filenames) && !in_array($gif_filename, $disp_filenames)) { // give preference to PNG or animated GIF
            array_push($disp_filenames, $filename);
        }
    }

    // Display, and include other extensions
    $other_exts = array('.pdf', '.jpg', '.png', '.gif', '.jpeg', '.jpg', '.eps', '.root', '.C', '.cc', '.cpp', '.cxx', '.txt', '.tex', '.log', '.dir', '.info', '.psd');
    natsort($disp_filenames); // natural sorting (for numbers)
    foreach ($disp_filenames as $filename) {
        array_push($displayed, $filename);
        $brfname = str_replace("_", "_<wbr>", $filename); //&shy;
        echo "<div class='pic'>\n";
        echo "<h3><a href=\"$filename\">$brfname</a></h3>";
        echo "<a href=\"$filename\"><img src=\"$filename\" style=\"border: none; max-width: 300px; max-height: 320px; \"></a>";
        $others = array();
        foreach ($other_exts as $ex) {
            $other_filename = preg_replace("~\.(png|gif)$~", $ex, $filename);
            if (strcmp($other_filename, $filename) == 0) continue;
            if (!file_exists($other_filename)) continue;
            array_push($others, "<a class=\"file\" href=\"$other_filename\">[" . $ex . "]</a>");
            if ($ex != '.txt') array_push($displayed, $other_filename);
        }
        if ($others) echo "<p>Also as " . implode(', ', $others) . "</p>";
        echo "</div>";
    }
}
?>
</div>

<div style="display: block; clear:both;">
<h2><a name="files">Other files</a></h2>
<ul>
<?php
foreach (glob("*") as $filename) {
    if (!isset($_GET['noplots']) || !$_GET['noplots'] || !in_array($filename, $displayed)) {
        if (isset($_GET['match'])) {
            if (isset($_GET['regexp']) && $_GET['regexp']) {
                if (!preg_match('/.*' . preg_quote($_GET['match'], '/') . '.*/', $filename)) continue;
            } else {
                if (!fnmatch('*' . $_GET['match'] . '*', $filename)) continue;
            }
        }
        if (is_dir($filename)) {
            echo "<li>[DIR] <b><a href=\"$filename\">$filename</a></b></li>";
        } else {
            echo "<li><a href=\"$filename\">$filename</a></li>";
        }
    }
}
?>
</ul>
</div>
<br>
</body>
</html>
