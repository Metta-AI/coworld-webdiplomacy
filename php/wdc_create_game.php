<?php
require __DIR__.'/wdc_bootstrap.php';
require_once 'gamemaster/game.php';
require_once 'gamemaster/member.php';
require_once 'lib/gamefiles.php';
$input = json_decode(stream_get_contents(STDIN), true, flags: JSON_THROW_ON_ERROR);
$DB->sql_put('BEGIN');
$Game = processGame::create(1, 'Coworld', '', 0, 'Unranked', $input['phase_minutes'],
    $input['retreat_build_minutes'], $input['phase_minutes'], 0, 1440,
    $input['anonymous'] ? 'Yes' : 'No', $input['press'], 'Normal', 'draw-votes-public', 0, 0, 'MemberVsBots');
$seats = array();
foreach ($input['tokens'] as $slot => $token) {
    $name = 'Seat'.($slot+1);
    $DB->sql_put("INSERT INTO wD_Users (username,email,type,timeJoined,timeLastSessionEnded,password)
        VALUES ('".$name."','seat".$slot."@example.invalid','User',UNIX_TIMESTAMP(),UNIX_TIMESTAMP(),UNHEX('".bin2hex(random_bytes(16))."'))");
    $userID = (int)$DB->last_inserted();
    // Match ApiKey::load()'s escaping convention, including HTML entities.
    $DB->sql_put("INSERT INTO wD_ApiKeys (userID,apiKey) VALUES (".$userID.",'".$DB->escape($token)."')");
    $country = $input['countries'][$slot];
    processMember::create($userID, 0, $country);
    $seats[] = array('slot'=>$slot, 'user_id'=>$userID, 'country_id'=>$country,
        'country'=>$Game->Variant->countries[$country-1]);
}
$DB->sql_put('COMMIT');
libGameFiles::refresh($Game->id);
ob_clean();
echo json_encode(array('ok'=>true, 'game_id'=>$Game->id, 'seats'=>$seats));
