<?php
require __DIR__.'/wdc_bootstrap.php';
require_once 'lib/gamefiles.php';
require_once 'lib/gamemessage.php';
$input = json_decode(stream_get_contents(STDIN), true, flags: JSON_THROW_ON_ERROR);
$gameID = (int)$argv[1];
$countryID = (int)$argv[2];
$toCountryID = (int)$input['toCountryID'];
$DB->sql_put('BEGIN');
$row = Game::fetchRow($gameID, UPDATE);
$code = null;
if (!$row || (int)$row['turn'] !== (int)$input['turn'] || $row['phase'] !== $input['phase']
    || $row['processStatus'] !== 'Not-processing' || (int)$row['processTime'] <= time()) {
    $code = 'window_closed';
} elseif ($row['pressType'] !== 'Regular' || $toCountryID < 0 || $toCountryID > 7 || $toCountryID === $countryID) {
    $code = 'invalid_action';
} else {
    $Variant = libVariant::loadFromVariantID($row['variantID']);
    $Game = $Variant->Game($row, NOLOCK);
    if (!isset($Game->Members->ByCountryID[$countryID]) || $Game->Members->ByCountryID[$countryID]->status !== 'Playing') {
        $code = 'seat_unavailable';
    } else {
        // Upstream inserts while the game row is locked, then commits before notification.
        libGameMessage::send($toCountryID, $countryID, $input['message']);
    }
}
$DB->sql_put('COMMIT');
ob_clean();
echo json_encode(array('ok'=>true, 'code'=>$code));
