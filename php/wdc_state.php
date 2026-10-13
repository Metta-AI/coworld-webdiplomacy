<?php
require __DIR__.'/wdc_bootstrap.php';
require_once 'lib/gamefiles.php';
$gameID = (int)$argv[1];
$DB->sql_put('START TRANSACTION WITH CONSISTENT SNAPSHOT');
$game = $DB->sql_hash('SELECT id,turn,phase,gameOver,processStatus,processTime,startTime FROM wD_Games WHERE id='.$gameID);
$members = array();
// Order status and API request counts are kept apart from the member rows: the
// adapter must never publish them during play (upstream hides order status in
// anonymous games). Each seat's user has exactly one key row; the key is never read.
$private = array();
$files = array();
if ($game) {
    $table = $DB->sql_tabl('SELECT m.countryID,m.status,m.supplyCenterNo,m.unitNo,m.orderStatus,k.hits
        FROM wD_Members m LEFT JOIN wD_ApiKeys k ON k.userID=m.userID
        WHERE m.gameID='.$gameID.' ORDER BY m.countryID');
    while ($row = $DB->tabl_hash($table)) {
        $private[] = array('countryID'=>$row['countryID'], 'order_status'=>$row['orderStatus'], 'api_requests'=>(int)$row['hits']);
        unset($row['orderStatus'], $row['hits']);
        $members[] = $row;
    }
    $row = libGameFiles::loadGameRow($gameID);
    $files = libGameFiles::urls($row, libGameFiles::state($gameID));
}
$DB->sql_put('COMMIT');
ob_clean();
echo json_encode(array('ok'=>true, 'game'=>$game ?: null, 'members'=>$members, 'private_activity'=>$private, 'files'=>$files));
