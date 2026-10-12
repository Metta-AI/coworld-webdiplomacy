<?php
require __DIR__.'/wdc_bootstrap.php';
$gameID = (int)$argv[1];
$countryID = (int)$argv[2];
$member = $DB->sql_hash('SELECT countryID FROM wD_Members WHERE gameID = '.$gameID.' AND countryID = '.$countryID);
if (!$member || $countryID < 1 || $countryID > 7) throw new RuntimeException('Unknown seat');
$table = !empty(Config::$allowBotsAccessToUnredactedMessages) ? 'wD_GameMessages' : 'wD_GameMessages_Redacted';
$rows = $DB->sql_tabl('SELECT id, turn, phaseMarker, timeSent, fromCountryID, toCountryID, message FROM '.$table
    .' WHERE gameID = '.$gameID.' AND toCountryID <> 0 AND (toCountryID = '.$countryID.' OR fromCountryID = '.$countryID.') ORDER BY id DESC LIMIT 17');
$messages = array();
while ($row = $DB->tabl_hash($rows)) {
    $messages[] = array('id'=>(int)$row['id'], 'turn'=>(int)$row['turn'], 'phase'=>$row['phaseMarker'],
        'timeSent'=>(int)$row['timeSent'], 'fromCountryID'=>(int)$row['fromCountryID'],
        'toCountryID'=>(int)$row['toCountryID'], 'message'=>$row['message']);
}
$truncated = count($messages) > 16;
ob_clean();
echo json_encode(array('ok'=>true, 'messages'=>array_reverse(array_slice($messages, 0, 16)), 'truncated'=>$truncated));
