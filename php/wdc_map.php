<?php
// Invoke the unmodified public renderer as a guest. Never request order previews.
chdir('/application');
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REMOTE_ADDR'] = '127.0.0.1';
$_SERVER['REQUEST_URI'] = '/map.php';
$_SERVER['SCRIPT_NAME'] = '/map.php';
$_SERVER['QUERY_STRING'] = '';
$_REQUEST = count($argv) === 1
    ? array('variantID'=>1)
    : array('gameID'=>(int)$argv[1], 'turn'=>(int)$argv[2], 'mapType'=>'small', 'nocache'=>1);
require 'map.php';
