pub(crate) const SECTOR_SIZE: usize = 512;
pub(crate) type Sector = [u8; SECTOR_SIZE];

pub(crate) trait BlockDevice {
    fn sector_count(&self) -> u32;
    fn read_sector(&mut self, lba: u32, sector: &mut Sector) -> Result<(), &'static str>;
    fn write_sector(&mut self, lba: u32, sector: &Sector) -> Result<(), &'static str>;
    fn flush(&mut self) -> Result<(), &'static str>;
}
