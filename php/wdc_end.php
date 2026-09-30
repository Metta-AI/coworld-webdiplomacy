<?php
require __DIR__.'/wdc_bootstrap.php';
require_once 'gamemaster/game.php';
require_once 'lib/gamefiles.php';
$gameID = (int)$argv[1];
list($locked) = $DB->sql_row("SELECT GET_LOCK('gamemaster',5)");
if (!$locked) {
    ob_clean();
    echo json_encode(array('ok'=>true, 'ended'=>false, 'busy'=>true));
    exit;
}
$DB->sql_put('BEGIN');
list($phase) = $DB->sql_row('SELECT phase FROM wD_Games WHERE id='.$gameID.' FOR UPDATE');
$ended = false;
if ($phase && $phase !== 'Finished') {
    $Variant = libVariant::loadFromVariantID(1);
    $Game = $Variant->processGame($gameID);
    $Game->setDrawn();
    $ended = true;
}
$DB->sql_put('COMMIT');
if ($phase) {
    libGameFiles::refresh($gameID);
    $Redis->trigger('private-game'.$gameID, 'overview', 'processed');
    Game::wipeCache($gameID);
}
$DB->sql_row("SELECT RELEASE_LOCK('gamemaster')");
ob_clean();
echo json_encode(array('ok'=>true, 'ended'=>$ended, 'busy'=>false));
