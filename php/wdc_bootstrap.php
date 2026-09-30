<?php
chdir('/application');
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REMOTE_ADDR'] = '127.0.0.1';
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/wdc.php';
$_SERVER['QUERY_STRING'] = '';
require 'header.php';
// header.php resets these limits, including for a CLI invocation.
ini_set('memory_limit', '256M');
ini_set('max_execution_time', '120');
