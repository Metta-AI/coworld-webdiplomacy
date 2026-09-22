<?php
chdir('/application');
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['REMOTE_ADDR'] = '127.0.0.1';
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/adapter.php';
$_SERVER['QUERY_STRING'] = '';
require 'header.php';
require_once 'gamemaster/game.php';
require_once 'gamemaster/member.php';
require_once 'gamemaster/gamemaster.php';
$DB->sql_put('BEGIN');
if ($argv[1] === 'create') {
    $Game = processGame::create(1, 'Coworld-local', '', 0, 'Unranked', 60, 60, 60, 0, 0, 'No', 'Regular', 'Normal', 'draw-votes-public', 0, 4, 'Members');
    for ($country = 1; $country <= 7; $country++) {
        list($userID) = $DB->sql_row("SELECT id FROM wD_Users WHERE username='bot".$country."'");
        processMember::create((int)$userID, 0, $country);
    }
    $Game->loadMembers();
    $Game->process();
} else {
    libGameMaster::findAndApplyGameVotes();
    $Variant = libVariant::loadFromVariantID(1);
    $Game = $Variant->processGame((int)$argv[2]);
    if ($argv[1] === 'draw') {
        $Game->setDrawn();
    } elseif ($Game->phase !== 'Finished') {
        $Game->process();
    }
}
$DB->sql_put('COMMIT');
ob_clean();
echo json_encode(['gameID' => $Game->id, 'phase' => $Game->phase, 'turn' => $Game->turn]);
