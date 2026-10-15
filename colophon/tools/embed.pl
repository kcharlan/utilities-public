#!/usr/bin/perl
use strict;
use warnings;
use FindBin;
use File::Path qw(make_path);
use File::Basename qw(dirname);
use File::Temp qw(tempfile);
die "usage: embed.pl OUTPUT.c\n" unless @ARGV == 1;
my $output = $ARGV[0];
my $temporary;
END { unlink $temporary if defined $temporary && -e $temporary; }
$SIG{INT} = $SIG{TERM} = $SIG{HUP} = sub { die "asset generation interrupted\n"; };
my %files = (page_template => 'page_template.html', font_css => 'font.css',
             page_css => 'page.css', page_js => 'page.js', ofl => 'OFL.txt',
             curated_bundled => 'curated_bundled.json', curated_price_history => 'curated_price_history.json',
             curated_bundled_claude => 'curated_bundled_claude.json',
             ccusage_fast_multiplier_overrides => 'ccusage_fast_multiplier_overrides.json');
sub read_bytes {
    my ($name) = @_;
    open my $file, '<:raw', "$FindBin::Bin/../assets/$name" or die "$name: $!\n";
    local $/;
    my $bytes = <$file>;
    die "$name: read failed: $!\n" if !defined($bytes) && !eof($file);
    close $file or die "$name: $!\n";
    return $bytes // '';
}

# Read every required input and validate ranges before creating any output.
my %bytes = map { $_ => read_bytes($files{$_}) } sort keys %files;
my %ranges;
for my $kind (qw(numeric extend prepend)) {
    my @pairs;
    for my $token (split /\s+/, read_bytes("pricing_${kind}_ranges.txt")) {
        next unless length $token;
        die "invalid range token: $token\n" unless $token =~ /^([0-9a-f]+)(?:-([0-9a-f]+))?$/;
        push @pairs, [hex($1), hex($2 // $1)];
    }
    die "empty $kind range table\n" unless @pairs;
    @pairs = sort { $a->[0] <=> $b->[0] } @pairs;
    my $previous = -1;
    for my $pair (@pairs) {
        die "overlapping/invalid $kind range\n" unless $pair->[0] > $previous && $pair->[0] <= $pair->[1] && $pair->[1] <= 0x10ffff;
        $previous = $pair->[1];
    }
    $ranges{$kind} = \@pairs;
}

# Publish only after successful writes and close. The sibling temporary file
# keeps rename atomic, and END removes failures without touching a prior target.
make_path(dirname($output));
my $out;
($out, $temporary) = tempfile('.assets.c.XXXXXX', DIR => dirname($output), UNLINK => 0);
binmode $out or die "$temporary: $!\n";
sub emit { print {$out} @_ or die "$temporary: write failed: $!\n"; }
emit "/* Generated from committed assets by tools/embed.pl. */\n#include \"gen/assets.h\"\n";
for my $name (sort keys %files) {
    my @bytes = (unpack('C*', $bytes{$name}), 0);
    emit "const unsigned char cp_asset_$name\[\] = {\n";
    while (@bytes) {
        emit '    ', join(',', splice(@bytes, 0, 24)), ",\n";
    }
    emit "};\nconst size_t cp_asset_${name}_len = sizeof(cp_asset_$name) - 1;\n";
}
for my $kind (qw(numeric extend prepend)) {
    emit "const uint32_t cp_pricing_${kind}_ranges[][2] = {\n";
    for my $pair (@{$ranges{$kind}}) {
        emit sprintf "    {0x%x, 0x%x},\n", @$pair;
    }
    emit "};\nconst size_t cp_pricing_${kind}_ranges_count = sizeof(cp_pricing_${kind}_ranges) / sizeof(cp_pricing_${kind}_ranges[0]);\n";
}
close $out or die "$temporary: close failed: $!\n";
rename $temporary, $output or die "$output: rename failed: $!\n";
undef $temporary;
