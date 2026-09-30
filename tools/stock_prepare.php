<?php
// Test fixture setup only; adjudication always remains with the stock SSE gamemaster.
require '/opt/php/wdc_bootstrap.php';
$DB->sql_put("UPDATE wD_Misc SET value=UNIX_TIMESTAMP() WHERE name='LastProcessTime'");
// Preserve past games while allowing another fixture's ordinary Seat1..Seat7 users.
$DB->sql_put("UPDATE wD_Users SET username=CONCAT('PreviousSeat',id), email=CONCAT('previous',id,'@example.invalid') WHERE username REGEXP '^Seat[1-7]$'");
$DB->sql_put("UPDATE wD_Games SET name=CONCAT('PreviousGame',id)");
$DB->sql_put('COMMIT');
ob_clean();
echo '{}';
