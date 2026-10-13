#!/usr/bin/perl
use strict;
use warnings;
use Digest::SHA qw(sha256_hex);
use JSON::PP qw(decode_json);
use FindBin;

my $assets = @ARGV ? shift @ARGV : "$FindBin::Bin/../assets";
die "usage: check_assets.pl [ASSET_DIRECTORY]\n" if @ARGV;
sub content {
    my ($path) = @_;
    open my $file, '<:raw', $path or die "cannot read $path: $!\n";
    local $/;
    my $bytes = <$file>;
    close $file or die "cannot close $path: $!\n";
    return $bytes;
}
my @expected = sort qw(OFL.txt curated_bundled.json curated_price_history.json font.css
    page.css page.js page_template.html pricing_extend_ranges.txt
    pricing_numeric_ranges.txt pricing_prepend_ranges.txt);
my $manifest = decode_json(content("$assets/MANIFEST"));
die "invalid asset manifest\n" unless ref($manifest) eq 'HASH' && ref($manifest->{assets}) eq 'HASH';
my @actual = sort keys %{$manifest->{assets}};
die "manifest must name exactly the ten expected assets\n" unless join('\0', @expected) eq join('\0', @actual);
for my $name (@expected) {
    my $digest = $manifest->{assets}{$name};
    die "invalid digest: $name\n" unless defined($digest) && !ref($digest) && $digest =~ /\A[0-9a-f]{64}\z/;
    die "digest mismatch: $name\n" unless sha256_hex(content("$assets/$name")) eq $digest;
}
print "10 local asset digests verified\n";
