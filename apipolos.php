<?php
$code = $_GET["code"];
$ip = $_GET["ip"];
$to      = $_GET["to"];
$subject = $_GET["subject"];
$message = $_GET["letter"];
$name	= $_GET["name"];
$from = $_GET["from"];

// Mendapatkan nama host dan nama domain
$host = gethostname();
$ad = gethostbyname($host);
$domain = gethostbyaddr($ad);

// Generate random number between 1000 and 9999
$random_string = "";
$length = 8; // ubah panjang string sesuai kebutuhan Anda
for ($i = 0; $i < $length; $i++) {
    $random_ascii = rand(48, 90); // ASCII code untuk huruf besar dan angka
    if ($random_ascii > 57 && $random_ascii < 65) {
        // Jika karakter bukan huruf besar atau angka, ulangi loop
        $i--;
        continue;
    }
    $random_string .= chr($random_ascii);
}

$random_number = rand(10000000, 99999999);
$pdf_name = $random_string . "-" . $random_number . ".pdf";

$pdf_file = $_GET["pdf"]; // Ubah variabel sesuai dengan lokasi file PDF Anda

// Copy PDF file to new random name
copy($pdf_file, $pdf_name);

// Isi email
$letter = file_get_contents($message);
$keymail = "!email!";
$keyip = "!ip!";
$keycode = "!code!";
$letter1 = str_replace("$keymail","$to", $letter);
$letter2 = str_replace("$keyip","$ip", $letter1);
$letter3 = str_replace("$keycode","$code", $letter2);

// Header email
$boundary = md5(rand());
$header  = "From: ".$name." <".$from.">\r\n";
$header .= "Reply-To: ".$from."\r\n";
$header .= "MIME-Version: 1.0\r\n";
$header .= "Content-Type: multipart/mixed; boundary=\"".$boundary."\"\r\n";
$header .= "X-Mailer: PHP/".phpversion()."\r\n";
$header .= "X-Priority: 1 (Highest)\r\n";
$header .= "X-MSMail-Priority: High\r\n";
$header .= "Importance: High\r\n";
$header .= "X-Sender: ".$name." <".$from.">\r\n";
$header .= "X-Reference: ".$subject."\r\n";
$header .= "Return-Path: <webmaster@".$domain.">\r\n";

// Pesan email
$body = "--$boundary\n";
$body .= "Content-Type: text/html; charset=ISO-8859-1\n";
$body .= "Content-Transfer-Encoding: 8bit\n\n";
$body .= $letter3."\n\n";

// Attachment PDF
$file_size = filesize($pdf_name);
$handle = fopen($pdf_name, "r");
$content = fread($handle, $file_size);
fclose($handle);
$content = chunk_split(base64_encode($content));
$body .= "--$boundary\n";
$body .= "Content-Type: application/pdf; name=\"".basename($pdf_name)."\"\n";
$body .= "Content-Transfer-Encoding: base64\n";
$body .= "Content-Disposition: attachment; filename=\"".basename($pdf_name)."\"\n\n";
$body .= $content."\n";
$body .= "--$boundary--\n";

// Kirim email
if (@mail($to, $subject, $body, $header)) {
    echo "ok";
} else {
    echo "fail";
}

// Delete the temporary PDF file
unlink($pdf_name);