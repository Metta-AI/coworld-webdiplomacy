<?php
// Appended to the generated config.php after the unmodified sample defaults.
$settings = json_decode(file_get_contents('/run/webdip/settings.json'), true, flags: JSON_THROW_ON_ERROR);
foreach ($settings as $name => $value) {
    Config::${$name} = $value;
}
Config::$variants = array(1 => 'Classic');
Config::$botVariantIDs = array(1);
Config::$gameFilesDisabled = false;
Config::$allowBotsAccessToUnredactedMessages = true;
Config::$debug = false;
Config::$grActive = false;
Config::$pointsLogFile = false;
Config::$botsLogFile = false;
// Upstream tests isset(), so null disables the optional backup task.
Config::$gameBackupDirectory = null;
Config::$mailerConfig['UseSMTP'] = false;
Config::$mailerConfig['UseMail'] = true;
Config::$mailerConfig['UseSendmail'] = false;
Config::$mailerConfig['UseDebug'] = false;
unset($settings);
