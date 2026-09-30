<?php
require __DIR__.'/wdc_bootstrap.php';
$Variant = libVariant::loadFromVariantID(1);
$fields = array(
    'variantID' => $Variant->id,
    'mapID' => $Variant->mapID,
    'supplyCenterTarget' => $Variant->supplyCenterTarget,
    'supplyCenterCount' => $Variant->supplyCenterCount,
    'countryCount' => count($Variant->countries),
    'name' => $Variant->name,
    'fullName' => $Variant->fullName,
    'description' => $Variant->description,
    'author' => $Variant->author,
    'countriesList' => implode(',', $Variant->countries),
);
$values = array();
foreach ($fields as $value) {
    $values[] = "'".$DB->escape((string)$value)."'";
}
$DB->sql_put('INSERT INTO wD_VariantInfo ('.implode(',', array_keys($fields)).') VALUES ('.implode(',', $values).')');
$DB->sql_put('COMMIT');
ob_clean();
echo json_encode(array('installed' => true, 'version' => VERSION, 'countries' => count($Variant->countries)))."\n";
