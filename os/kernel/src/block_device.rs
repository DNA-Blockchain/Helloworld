pub(crate) const SECTOR_SIZE: usize = 512;
pub(crate) type Sector = [u8; SECTOR_SIZE];

pub(crate) trait BlockDevice {
    fn sector_count(&self) -> u32;
    fn read_sector(&mut self, lba: u32, sector: &mut Sector) -> Result<(), &'static str>;
    fn write_sector(&mut self, lba: u32, sector: &Sector) -> Result<(), &'static str>;
    fn flush(&mut self) -> Result<(), &'static str>;
}
/*
 * Copyright (c) 2026 Chase Allen Ringquist. All rights reserved.
 *
 * This file is part of an operating system, software, and network Work
 * conceived and authored by Chase Allen Ringquist. It is the intellectual and
 * digital property of the Author, except where an open-source license
 * accompanying this file expressly grants other rights.
 *
 * Do not remove or alter this notice or any record of origin.
 * See NOTICE.md in the project root for full terms.
 * See LICENSE for the applicable license.
 *
 * Contact:  ringquistchase@gmail.com  |  (918) 845-0940
 *            Bixby, OK, United States
 */
