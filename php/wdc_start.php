<?php
require __DIR__.'/wdc_bootstrap.php';
$gameID = (int)$argv[1];
$DB->sql_put("UPDATE wD_Games SET processTime=UNIX_TIMESTAMP() WHERE id=".$gameID." AND phase='Pre-game'");
$DB->sql_put('COMMIT');
Game::wipeCache($gameID);
ob_clean();
echo json_encode(array('ok'=>true));
