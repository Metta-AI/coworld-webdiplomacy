<?php
require __DIR__.'/wdc_bootstrap.php';
require_once 'lib/gamefiles.php';
$gameID = (int)$argv[1];
$DB->sql_put('START TRANSACTION WITH CONSISTENT SNAPSHOT');
$game = $DB->sql_hash('SELECT id,turn,phase,gameOver,processStatus,processTime,startTime FROM wD_Games WHERE id='.$gameID);
$members = array();
$files = array();
if ($game) {
    $table = $DB->sql_tabl('SELECT countryID,status,supplyCenterNo,unitNo FROM wD_Members WHERE gameID='.$gameID.' ORDER BY countryID');
    while ($row = $DB->tabl_hash($table)) $members[] = $row;
    $row = libGameFiles::loadGameRow($gameID);
    $files = libGameFiles::urls($row, libGameFiles::state($gameID));
}
$DB->sql_put('COMMIT');
ob_clean();
echo json_encode(array('ok'=>true, 'game'=>$game ?: null, 'members'=>$members, 'files'=>$files));
