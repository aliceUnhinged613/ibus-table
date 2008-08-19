# -*- coding: utf-8 -*-
# vim: set noet ts=4:
#
# ibus-table
#
# Copyright (c) 2008-2008 Yu Yuwei <acevery@gmail.com>
#
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330,
# Boston, MA  02111-1307  USA
#
# $Id: $
#
__all__ = (
	"tabengine",
)

import os
import ibus
from ibus import Property
from ibus import keysyms
from ibus import modifier
from ibus import ascii
import tabsqlitedb
import tabdict
import re
patt_edit = re.compile (r'(.*)###(.*)###(.*)')
patt_uncommit = re.compile (r'(.*)@@@(.*)')

from gettext import dgettext
_  = lambda a : dgettext ("ibus-table", a)
N_ = lambda a : a


class KeyEvent:
	def __init__(self, keyval, is_press, state):
		self.code = keyval
		self.mask = state
		if not is_press:
			self.mask |= modifier.RELEASE_MASK
	def __str__(self):
		return "%s 0x%08x" % (keysyms.keycode_to_name(self.code), self.mask)


class editor:
	'''Hold user inputs chars and preedit string'''
	def __init__ (self,phrase_table_index,valid_input_chars, max_key_length, database, parser = tabdict.parse, deparser = tabdict.deparse, max_length = 64):
		self.db = database
		self._pt = phrase_table_index
		self._parser = parser
		self._deparser = deparser
		self._max_key_len = int(max_key_length)
		self._max_length = max_length
		self._valid_input_chars = valid_input_chars
		#
		# below vals will be reset in self.clear()
		#
		# we hold this: [str,str,...]
		# self._chars: hold user input in table mode (valid,invalid,prevalid)
		self._chars = [[],[],[]]
		#self._t_chars: hold total input for table mode for input check
		self._t_chars = []
		# self._u_chars: hold user input but not manual comitted chars
		self._u_chars = []
		# self._tabkey_list: hold tab_key objects transform from user input chars
		self._tabkey_list = []
		# self._strings: hold preedit strings
		self._strings = []
		# self._cursor: the caret position in preedit phrases 
		self._cursor = [0,0]
		# self._candidates: hold candidates selected from database [[now],[pre]]
		self._candidates = [[],[]]
		self._lookup_table = ibus.LookupTable (tabengine._page_size)
		# self._py_mode: whether in pinyin mode
		self._py_mode = False
		# self._zi: the last Zi commit to preedit
		self._zi = u''
		# self._caret: caret position in lookup_table
		self._caret = 0

	def clear (self):
		'''Remove data holded'''
		self.over_input ()
		self._t_chars = []
		self._strings = []
		self._cursor = [0,0]
		self._py_mode = False
		self._zi = u''
		self.update_candidates
	
	def is_empty (self):
		return len(self._t_chars) == 0

	def clear_input (self):
		'''
		Remove input characters held for Table mode,
		'''
		self._chars = [[],[],[]]
		self._tabkey_list = []
		self._lookup_table.clean()
		self._lookup_table.show_cursor(False)
		self._candidates = [[],[]]
	
	def over_input (self):
		'''
		Remove input characters held for Table mode,
		'''
		self.clear_input ()
		self._u_chars = []
	
	def set_parser (self, parser):
		'''change input parser'''
		self.clear ()
		self._parser = parser
		
	def add_input (self,c):
		'''add input character'''
		if len (self._t_chars) == self._max_length:
			return
		self._zi = u''
		if self._cursor[1]:
			self.split_phrase()
		if (len (self._chars[0]) == self._max_key_len and (not self._py_mode)) or ( len (self._chars[0]) == 6 and self._py_mode ) :
			self.auto_commit_to_preedit()
			res = self.add_input (c)
			return res
		elif self._chars[1]:
			self._chars[1].append (c)
		else:
			if (not self._py_mode and ( c in self._valid_input_chars)) or\
				(self._py_mode and (c in u'abcdefghijklmnopqrstuvwxyz')):
				try:
					self._tabkey_list += self._parser (c)
					self._chars[0].append (c)
				except:
					self._chars[1].append (c)
			else:
				self._chars[1].append (c)
		self._t_chars.append(c)
		res = self.update_candidates ()
		return res

	def pop_input (self):
		'''remove and display last input char held'''
		_c =''
		if self._chars[1]:
			_c = self._chars[1].pop ()
		elif self._chars[0]:
			_c = self._chars[0].pop ()
			self._tabkey_list.pop()
			if (not self._chars[0]) and self._u_chars:
				self._chars[0] = self._u_chars.pop()
				self._chars[1] = self._chars[1][:-1]
				self._tabkey_list = self._parser (self._chars[0])
				self._strings.pop (self._cursor[0] - 1 )
				self._cursor[0] -= 1
		self._t_chars.pop()
		self.update_candidates ()
		return _c
	
	def get_input_chars (self):
		'''get characters held, valid and invalid'''
		return self._chars[0] + self._chars[1]

	def get_input_chars_string (self):
		'''Get valid input char string'''
		return u''.join(map(str,self._t_chars))

	def get_all_input_strings (self):
		'''Get all uncommit input characters, used in English mode or direct commit'''
		return  u''.join( map(u''.join, self._u_chars + [self._chars[0]]) )
	
	def get_index(self,key):
		'''Get the index of key in database table'''
		return self._pt.index(key)

	def split_phrase (self):
		'''Splite current phrase into two phrase'''
		_head = u''
		_end = u''
		try:
			_head = self._strings[self._cursor[0]][:self._cursor[1]]
			_end = self._strings[self._cursor[0]][self._cursor[1]:]
			self._strings.pop(self._cursor[0])
			self._strings.insert(self._cursor[0],_head)
			self._strings.insert(self._cursor[0]+1,_end)
			self._cursor[0] +=1
			self._cursor[1] = 0
		except:
			pass
	
	def remove_before_string (self):
		'''Remove string before cursor'''
		if self._cursor[1] != 0:
			self.split_phrase()
		if self._cursor[0] > 0:
			self._strings.pop(self._cursor[0]-1)
			self._cursor[0] -= 1
		else:
			pass
		# if we remove all characters in preedit string, we need to clear the self._t_chars
		if self._cursor == [0,0]:
			self._t_chars =[]
	
	def remove_after_string (self):
		'''Remove string after cursor'''
		if self._cursor[1] != 0:
			self.split_phrase()
		if self._cursor[0] >= len (self._strings):
			pass
		else:
			self._strings.pop(self._cursor[0])
	
	def remove_before_char (self):
		'''Remove character before cursor'''
		if self._cursor[1] > 0:
			_str = self._strings[ self._cursor[0] ]
			self._strings[ self._cursor[0] ] = _str[ : self._cursor[1]-1] + _str[ self._cursor[1] :]
			self._cursor[1] -= 1
		else:
			if self._cursor[0] == 0:
				pass
			else:
				if len ( self._strings[self._cursor[0] - 1] ) == 1:
					self.remove_before_string()
				else:
					self._strings[self._cursor[0] - 1] = self._strings[self._cursor[0] - 1][:-1]
		# if we remove all characters in preedit string, we need to clear the self._t_chars
		if self._cursor == [0,0]:
			self._t_chars =[]

	def remove_after_char (self):
		'''Remove character after cursor'''
		if self._cursor[1] == 0:
			if self._cursor[0] == len ( self._strings):
				pass
			else:
				if len( self._strings[ self._cursor[0] ]) == 1:
					self.remove_after_string ()
				else:
					self._strings[ self._cursor[0] ] = self._strings[ self._cursor[0] ][1:]
		else:
			if ( self._cursor[1] + 1 ) == len( self._strings[ self._cursor[0] ] ) :
				self.split_phrase ()
				self.remove_after_string ()
			else:
				string = self._strings[ self._cursor[0] ]
				self._strings[ self._cursor[0] ] = string[:self._cursor[1]] + string[ self._cursor[1] + 1 : ]

	def get_invalid_input_chars (self):
		'''get invalid characters held'''
		return self._chars[1]

	def get_invalid_input_string (self):
		'''get invalid characters in string form'''
		return u''.join (self._chars[1])
		
	def get_preedit_strings (self):
		'''Get preedit strings'''
		if self._candidates[0]:
			if self._py_mode:
				_p_index = 7
			else:
				_p_index = self.get_index ('phrase')
			_candi = u'###' + self._candidates[0][ int (self._lookup_table.get_cursor_pos() ) ][ _p_index ] + u'###' 
		else:
			input_chars = self.get_input_chars ()
			if input_chars:
				_candi = u''.join( ['###'] + map( str, input_chars) + ['###'] )
			else:
				_candi = u''
		if self._strings:
			res = u''
			_cursor = self._cursor[0]
			_luc = len (self._u_chars)
			if _luc:
				res =u''.join( self._strings[ : _cursor - _luc] +[u'@@@'] + self._strings[_cursor - _luc : _cursor ]  + [ _candi  ] + self._strings[ _cursor : ])
			else:
				res = u''.join( self._strings[ : _cursor ] + [ _candi  ] + self._strings[ _cursor : ])
			return res
		else:
			return _candi
	def add_caret (self, addstr):
		'''add length to caret position'''
		self._caret += len(addstr)

	def get_caret (self):
		'''Get caret position in preedit strings'''
		self._caret = 0
		if self._cursor[0] and self._strings:
			map (self.add_caret,self._strings[:self._cursor[0]])
		self._caret += self._cursor[1]
		if self._candidates[0]:
			if self._py_mode:
				_p_index = 7
			else:
				_p_index = self.get_index ('phrase')
			_candi =self._candidates[0][ int (self._lookup_table.get_cursor_pos() ) ][ _p_index ] 
		else:
			_candi = u''.join( map( str,self.get_input_chars()) )
		self._caret += len( _candi ) 
		return self._caret
	
	def arrow_left (self):
		'''Process Arrow Left Key Event.
		Update cursor data when move caret left'''
		if self.get_preedit_strings ():
			if not( self.get_input_chars () or self._u_chars ):
				if self._cursor[1] > 0:
					self._cursor[1] -= 1
				else:
					if self._cursor[0] > 0:
						self._cursor[1] = len (self._strings[self._cursor[0]-1]) - 1
						self._cursor[0] -= 1
					else:
						self._cursor[0] = len(self._strings)
						self._cursor[1] = 0
				self.update_candidates ()
			return True
		else:
			return False
	
	def arrow_right (self):
		'''Process Arrow Right Key Event.
		Update cursor data when move caret right'''
		if self.get_preedit_strings ():
			if not( self.get_input_chars () or self._u_chars ):
				if self._cursor[1] == 0:
					if self._cursor[0] == len (self._strings):
						self._cursor[0] = 0
					else:
						self._cursor[1] += 1
				else:
					self._cursor[1] += 1
				if self._cursor[1] == len(self._strings[ self._cursor[0] ]):
					self._cursor[0] += 1
					self._cursor[1] = 0
				self.update_candidates ()
			return True
		else:
			return False

	def control_arrow_left (self):
		'''Process Control + Arrow Left Key Event.
		Update cursor data when move caret to string left'''
		if self.get_preedit_strings ():
			if not( self.get_input_chars () or self._u_chars ):
				if self._cursor[1] == 0:
					if self._cursor[0] == 0:
						self._cursor[0] = len (self._strings) - 1
					else:
						self._cursor[0] -= 1
				else:
					self._cursor[1] = 0
				self.update_candidates ()
			return True
		else:
			return False
	
	def control_arrow_right (self):
		'''Process Control + Arrow Right Key Event.
		Update cursor data when move caret to string right'''
		if self.get_preedit_strings ():
			if not( self.get_input_chars () or self._u_chars ):
				if self._cursor[1] == 0:
					if self._cursor[0] == len (self._strings):
						self._cursor[0] = 1
					else:
						self._cursor[0] += 1
				else:
					self._cursor[0] += 1
					self._cursor[1] = 0
				self.update_candidates ()
			return True
		else:
			return False
	def ap_candidate (self, candi):
		'''append candidate to lookup_table'''
		if not self._py_mode:
			_p_index = self.get_index('phrase')
			_fkey = self.get_index('m0')
		else:
			_p_index = 7
			_fkey = 1
		_phrase = candi[_p_index]
		_tbks = u''.join( map(self._deparser , candi[_fkey + len(self._tabkey_list) : _p_index ] ) )
		# further color implementation needed :)
		# here -2 is the pos of num, -1 is the pos of . 0 is the pos of string
		#attrs = ibus.AttrList ([ibus.AttributeForeground (0x8e2626, -2, 1)])
		attrs = ibus.AttrList ()
		if candi[-2] == -1:
			# this is a user defined phrase:
			attrs.append ( ibus.AttributeForeground (0x7700c3, 0, len(_phrase)) )
		elif candi[-1] > 0:
			# this is a sys phrase used by user:
			attrs.append ( ibus.AttributeForeground (0x000000, 0, len(_phrase)) )
		else:
			# this is a system phrase haven't been used:
			attrs.append ( ibus.AttributeForeground (0x000000, 0, len(_phrase)) )
		# this is the part of tabkey
		attrs.append( ibus.AttributeForeground ( 0x1973a2, len(_phrase), len(_tbks)) )
		self._lookup_table.append_candidate ( _phrase + _tbks, attrs )
		self._lookup_table.show_cursor (True)

	def update_candidates (self):
		'''Update lookuptable'''
		if self._chars[0] == self._chars[2] and self._candidates[0]:
			# if no change in valid input char, we do not do sql enquery
			pass
		else:
			# do enquiry
			self._lookup_table.clean ()
			self._lookup_table.show_cursor (False)
			if self._tabkey_list:
				# here we need to consider two parts, table and pinyin
				# first table
				if not self._py_mode:
					self._candidates[0] = self.db.select_words( self._tabkey_list )
				else:
					self._candidates[0] = self.db.select_zi( self._tabkey_list )
				self._chars[2] = self._chars[0][:]
					
			else:
				self._candidates[0] =[]
			if self._candidates[0]:
				map ( self.ap_candidate, self._candidates[0])
			else:
				if self._chars[0]:
					if self._candidates[1]:
						#print self._candidates[1]
						self._candidates[0] = self._candidates[1]
						self._candidates[1] = []
						last_input = self.pop_input ()
						self.auto_commit_to_preedit ()
						res = self.add_input( last_input )
						return res
					else:
						self.pop_input ()
						self._lookup_table.clean()
						self._lookup_table.show_cursor (False)
						return False
						
				else:
					self._lookup_table.clean()
					self._lookup_table.show_cursor (False)
			self._candidates[1] = self._candidates[0]
		return True	

	def commit_to_preedit (self):
		'''Add select phrase in lookup table to preedit string'''
		if not self._py_mode:
			_p_index = self.get_index('phrase')
		else:
			_p_index = 7
		try:
			self._strings.insert(self._cursor[0], self._candidates[0][ self.get_cursor_pos() ][_p_index])
			self._cursor [0] += 1
			if self._py_mode:
				self._zi = self._candidates[0][ self.get_cursor_pos() ][_p_index]
			self.over_input ()
			self.update_candidates ()
		except:
			pass
	
	def auto_commit_to_preedit (self):
		'''Add select phrase in lookup table to preedit string'''
		if not self._py_mode:
			_p_index = self.get_index('phrase')
		else:
			_p_index = 7
		try:
			self._u_chars.append( self._chars[0][:] )
			self._strings.insert(self._cursor[0], self._candidates[0][ self.get_cursor_pos() ][_p_index])
			self._cursor [0] += 1
			self.clear_input()
			self.update_candidates ()
		except:
			pass

	def get_aux_strings (self):
		'''Get aux strings'''
		input_chars = self.get_input_chars ()
		if input_chars:
			#aux_string =  u' '.join( map( u''.join, self._u_chars + [self._chars[0]] ) )
			aux_string =   u''.join (self._chars[0]) 
			return aux_string

		aux_string = u''
		if self._zi:
			# we have pinyin result
			tabcodes = self.db.find_zi_code(self._zi)
			aux_string = self._zi+u': '
			aux_string = u' '.join(tabcodes)
		#	self._zi = u''
		cstr = u''.join(self._strings)
		if self.db.user_can_define_phrase:
			if len (cstr ) > 1:
				aux_string += (u'\t#: ' + self.db.parse_phrase_to_tabkeys (cstr))
		return aux_string
	def arrow_down(self):
		'''Process Arrow Down Key Event
		Move Lookup Table cursor down'''
		res = self._lookup_table.cursor_down()
		self.update_candidates ()
		if not res and self._candidates[0]:
			return True
		return res
	
	def arrow_up(self):
		'''Process Arrow Up Key Event
		Move Lookup Table cursor up'''
		res = self._lookup_table.cursor_up()
		self.update_candidates ()
		if not res and self._candidates[0]:
			return True
		return res
	
	def page_down(self):
		'''Process Page Down Key Event
		Move Lookup Table page down'''
		res = self._lookup_table.page_down()
		self.update_candidates ()
		if not res and self._candidates[0]:
			return True
		return res
	
	def page_up(self):
		'''Process Page Up Key Event
		move Lookup Table page up'''
		res = self._lookup_table.page_up()
		self.update_candidates ()
		if not res and self._candidates[0]:
			return True
		return res
	
	def number (self, index):
		'''Select the candidates in Lookup Table
		index should start from 0'''
		self._lookup_table.set_cursor_pos_in_current_page ( index )
		if index != self._lookup_table.get_cursor_pos_in_current_page ():
			# the index given is out of range we do not commit string
			return False
		self.commit_to_preedit ()
		return True

	def alt_number (self,index):
		'''Remove the candidates in Lookup Table from user_db index should start from 0'''
		cps = self._lookup_table.get_current_page_start()
		pos = cps + index
		if  len (self._candidates[0]) > pos:
			# this index is valid
			can = self._candidates[0][pos]
			if can[-2] == -1:
				# freq of this candidate is -1, means this a user phrase
				self.db.remove_phrase (can)
				# make update_candidates do sql enquiry
				self._chars[2].pop()
				self.update_candidates ()
			return True
		else:
			return False

	def get_cursor_pos (self):
		'''get lookup table cursor position'''
		return self._lookup_table.get_cursor_pos()

	def get_lookup_table (self):
		'''Get lookup table'''
		return self._lookup_table

	def is_lt_visible (self):
		'''Check whether lookup table is visible'''
		return self._lookup_table.is_cursor_visible ()
	
	def backspace (self):
		'''Process backspace Key Event'''
		self._zi = u''
		if self.get_input_chars():
			self.pop_input ()
			return True
		elif self.get_preedit_strings ():
			self.remove_before_char ()
			return True
		else:
			return False
	
	def control_backspace (self):
		'''Process control+backspace Key Event'''
		self._zi = u''
		if self.get_input_chars():
			self.over_input ()
			return True
		elif self.get_preedit_strings ():
			self.remove_before_string ()
			return True
		else:
			return False

	def delete (self):
		'''Process delete Key Event'''
		self._zi = u''
		if self.get_input_chars():
			return True
		elif self.get_preedit_strings ():
			self.remove_after_char ()
			return True
		else:
			return False
	
	def control_delete (self):
		'''Process control+delete Key Event'''
		self._zi = u''
		if self.get_input_chars ():
			return True
		elif self.get_preedit_strings ():
			self.remove_after_string ()
			return True
		else:
			return False

	def l_shift (self):
		'''Process Left Shift Key Event as immediately commit to preedit strings'''
		if self._chars[0]:
			self.commit_to_preedit ()
			return True
		else:
			return False
	
	def r_shift (self):
		'''Proess Right Shift Key Event as changed between PinYin Mode and Table Mode'''
		self._zi = u''
		if self._chars[0]:
			self.commit_to_preedit ()
		self._py_mode = not (self._py_mode)
		return True

	def space (self):
		'''Process space Key Event
		return (KeyProcessResult,whethercommit,commitstring)'''
		if self._t_chars :
			# user has input sth
			self.commit_to_preedit ()
			pstr = self.get_preedit_strings ()
			self.clear()
			return (True,pstr)
		else:
			return (False,u'')

class tabengine (ibus.EngineBase):
	'''The IM Engine for Tables'''
	
	# colors
#	_phrase_color 			= 0xffffff
#	_user_phrase_color 		= 0xffffff
#	_new_phrase_color 		= 0xffffff

	# lookup table page size
	_page_size = 6

	def __init__ (self, bus, obj_path, db ):
		super(tabengine,self).__init__ (bus,obj_path)
		self._lookup_table = ibus.LookupTable (tabengine._page_size)
		# this is the backend sql db we need for our IME
		# we receive this db from IMEngineFactory
		#self.db = tabsqlitedb.tabsqlitedb( name = dbname )
		self.db = db 
		# this is the parer which parse the input string to key object
		self._parser = tabdict.parse
		
		self._icon_dir = '%s%s%s%s' % (os.getenv('IBUS_TABLES_LOCATION'),
				os.path.sep, 'icons', os.path.sep)
		# 0 = english input mode
		# 1 = table input mode
		self._mode = 1
		# self._ime_py: True / False this IME support pinyin mode
		self._ime_py = self.db.get_ime_property ('pinyin_mode')
		if self._ime_py:
			if self._ime_py.lower() == u'true':
				self._ime_py = True
			else:
				self._ime_py = False
		else:
			print 'We coult not find "pinyin_mode" entry in database, is it a outdated database?'
			self._ime_py = False

		self._status = self.db.get_ime_property('status_prompt').encode('utf8')
		# now we check and update the valid input characters
		self._chars = self.db.get_ime_property('valid_input_chars')
		self._valid_input_chars = []
		for _c in self._chars:
			if _c in tabdict.tab_key_list:
				self._valid_input_chars.append(_c)
		del self._chars
		self._pt = self.db.get_phrase_table_index ()
		self._ml = int(self.db.get_ime_property ('max_key_length'))
		
		# Containers we used:
		self._editor = editor(self._pt, self._valid_input_chars, self._ml, self.db)

		# some other vals we used:
		# self._prev_key: hold the key event last time.
		self._prev_key = None
		self._prev_char = None
		self._double_quotation_state = False
		self._single_quotation_state = False
		# [ENmode,TABmode] we get TABmode properties from db
		self._full_width_letter = [
				False, 
				self.db.get_ime_property('def_full_width_letter').lower() == u'true'
				]
		self._full_width_punct = [
				False,
				self.db.get_ime_property('def_full_width_punct').lower() == u'true'
				]
		
		# some properties we will involved, Property is taken from scim.
		#self._setup_property = Property ("setup", _("Setup"))
		self.reset ()
		

	def reset (self):
		self._editor.clear ()
		self._double_quotation_state = False
		self._single_quotation_state = False
		self._prev_key = None
		self._init_properties ()
		self._update_ui ()

	def _init_properties (self):
		self.properties= ibus.PropList ()
		self._status_property = ibus.Property(u'status')
		self._letter_property = ibus.Property(u'letter')
		self._punct_property = ibus.Property(u'punct')
		self._py_property = ibus.Property(u'py_mode')
		for prop in (self._status_property,
			self._letter_property,
			self._punct_property,
			self._py_property 
			#self._setup_property
			):
			self.properties.append(prop)

		self.register_properties (self.properties)
		self._refresh_properties ()
	
	def _refresh_properties (self):
		'''Method used to update properties'''
		# taken and modified from PinYin.py :)
		if self._mode == 1: # refresh mode
			self._status_property.set_label(  _(self._status) )
			self._status_property.set_tooltip (  _(u'Switch to English mode') )
		else:
			self._status_property.set_label( _(u'EN') )
			self._status_property.set_tooltip (  _(u'Switch to Table mode') )

		if self._full_width_letter[self._mode]:
			self._letter_property.set_icon ( u'%s%s' % (self._icon_dir, 'full-letter.svg') )
			self._letter_property.set_tooltip ( _(u'Switch to half letter') )
		else:
			self._letter_property.set_icon ( u'%s%s' % (self._icon_dir, 'half-letter.svg') )
			self._letter_property.set_tooltip ( _(u'Switch to full letter') )

		if self._full_width_punct[self._mode]:
			self._punct_property.set_icon ( u'%s%s' % (self._icon_dir, 'full-punct.svg') )
			self._punct_property.set_tooltip ( _( u'Switch to half punction' ) )
		else:
			self._punct_property.set_icon ( u'%s%s' % (self._icon_dir,'half-punct.svg' ) )
			self._punct_property.set_tooltip ( _( u'Switch to full punction' ) )
		
		if self._editor._py_mode:
			self._py_property.set_icon ( u'%s%s' % (self._icon_dir, 'py-mode.svg' ) )
			self._py_property.set_tooltip ( _(u'Switch to Table mode') )
		
		else:
			self._py_property.set_icon ( u'%s%s' % (self._icon_dir, 'tab-mode.svg' ) )
			self._py_property.set_tooltip ( _(u'Switch to PinYin mode') )

		# use buildin method to update properties :)
		map (self.update_property, self.properties)
	
	def _change_mode (self):
		'''Shift input mode, TAB -> EN -> TAB
		'''
		self._mode = int (not self._mode)
		self.reset ()
		self._update_ui ()

	def property_activate (self, property,prop_state = ibus.PROP_STATE_UNCHECKED):
		'''Shift property'''
		if property == u"status":
			self._change_mode ()
		elif property == u'letter':
			self._full_width_letter [self._mode] = not self._full_width_letter [self._mode]
		elif property == u'punct':
			self._full_width_punct [self._mode] = not self._full_width_punct [self._mode]
		elif property == u'py_mode' and self._ime_py:
			self._editor.r_shift ()
		self._refresh_properties ()
	#	elif property == "setup":
			# Need implementation
	#		self.start_helper ("96c07b6f-0c3d-4403-ab57-908dd9b8d513")
		# at last invoke default method 
	
	def _update_preedit (self):
		'''Update Preedit String in UI'''
		_str = self._editor.get_preedit_strings ()
		if _str == u'':
			self.update_preedit (u'', None, 0, False)
		else:
			attrs = ibus.AttrList()
			res = patt_edit.match (_str)
			if res:
				_str = u''
				ures = patt_uncommit.match (res.group(1))
				if ures:
					_str=u''.join (ures.groups())
					lc = len (ures.group(1) )
					lu = len (ures.group(2) )
					attrs.append (ibus.AttributeForeground(0x1b3f03,0,lc) )
					attrs.append (ibus.AttributeForeground(0x0895a2,lc,lu) )
					lg1 = len (_str)
				else:
					_str += res.group (1)
					lg1 = len ( res.group(1) )
					attrs.append (ibus.AttributeForeground(0x1b3f03,0,lg1) )
				_str += res.group(2)
				_str += res.group(3)
				lg2 = len ( res.group(2) )
				lg3 = len ( res.group(3) )
				attrs.append( ibus.AttributeForeground(0x0e0ea0,lg1,lg2) )
				attrs.append( ibus.AttributeForeground(0x1b3f03,lg1+lg2,lg3) )
			else:
				attrs.append( ibus.AttributeForeground(0x1b3f03,0,len(_str)) )
			# because ibus now can only insert preedit into txt, so...
			attrs = ibus.AttrList()
			attrs.append(ibus.AttributeUnderline(ibus.ATTR_UNDERLINE_SINGLE, 0, len(_str)))


			self.update_preedit (_str, attrs, self._editor.get_caret(), True)
	
	def _update_aux (self):
		'''Update Aux String in UI'''
		_ic = self._editor.get_aux_strings ()
		if _ic:
			attrs = ibus.AttrList([ ibus.AttributeForeground(0x9515b5,0, len(_ic)) ])
			#attrs = [ scim.Attribute(0,len(_ic),scim.ATTR_FOREGROUND,0x5540c1)]

			self.update_aux_string (_ic, attrs, True)
		else:
			self.hide_aux_string ()
			self.update_aux_string (u'', None, False)

	def _update_lookup_table (self):
		'''Update Lookup Table in UI'''
		
		self.update_lookup_table ( self._editor.get_lookup_table(), True, True )	
		if self._editor.is_empty ():
			self.hide_lookup_table()

	def _update_ui (self):
		'''Update User Interface'''
		self._update_lookup_table ()
		self._update_preedit ()
		self._update_aux ()
	
	def commit_string (self,string):
		super(tabengine,self).commit_string ( string )
		self._prev_char = string[-1]

	def _convert_to_full_width (self, c):
		'''convert half width character to full width'''
		if c in [u".", u"\\", u"^", u"_", u"$", u"\"", u"'", u">", u"<" ]:
			if c == u".":
				if self._prev_char and self._prev_char.isdigit () \
					and self._prev_key and chr (self._prev_key.code) == self._prev_char:
					return u"."
				else:
					return u"\u3002"
			elif c == u"\\":
				return u"\u3001"
			elif c == u"^":
				return u"\u2026\u2026"
			elif c == u"_":
				return u"\u2014\u2014"
			elif c == u"$":
				return u"\uffe5"
			elif c == u"\"":
				self._double_quotation_state = not self._double_quotation_state
				if self._double_quotation_state:
					return u"\u201c"
				else:
					return u"\u201d"
			elif c == u"'":
				self._single_quotation_state = not self._single_quotation_state
				if self._single_quotation_state:
					return u"\u2018"
				else:
					return u"\u2019"
			elif c == u"<":
				if self._mode:
					return u"\u300a"
			elif c == u">":
				if self._mode:
					return u"\u300b"
			
		return ibus.unichar_half_to_full (c)
	
	def _match_hotkey (self, key, code, mask):
		
		if key.code == code and key.mask == mask:
			if self._prev_key and key.code == self._prev_key.code and key.mask & modifier.RELEASE_MASK:
				return True
			if not key.mask & modifier.RELEASE_MASK:
				return True

		return False
	
	def process_key_event(self, keyval, is_press, state):
		'''Process Key Events
		Key Events include Key Press and Key Release,
		modifier means Key Pressed
		'''
		key = KeyEvent (keyval, is_press, state)
		result = self._process_key_event (key)
		self._prev_key = key
		return result

	def _process_key_event (self, key):
		'''Internal method to process key event'''
		# Match mode switch hotkey
		if not self._editor._t_chars and ( self._match_hotkey (key, keysyms.Shift_L, modifier.SHIFT_MASK + modifier.RELEASE_MASK)):
			self._change_mode ()
			return True

		# Match full half letter mode switch hotkey
		if self._match_hotkey (key, keysyms.space, modifier.SHIFT_MASK):
			self.property_activate ("letter")
			return True
		
		# Match full half punct mode switch hotkey
		if self._match_hotkey (key, keysyms.period, modifier.CONTROL_MASK):
			self.property_activate ("punct")
			return True
		
		# we ignore all hotkeys
#		if key.mask & modifier.ALT_MASK:
#			return False

		# Ignore key release event
#		if key.mask & modifier.RELEASE_MASK:
#			return True
		
		if self._mode:
			return self._table_mode_process_key_event (key)
		else:
			return self._english_mode_process_key_event (key)

	def _english_mode_process_key_event (self, key):
		'''English Mode Process Key Event'''
		# Ignore key release event
		if key.mask & modifier.RELEASE_MASK:
			return True
		
		if key.code >= 128:
			return False
		# we ignore all hotkeys here	
		if key.mask & modifier.CONTROL_MASK+modifier.ALT_MASK:
			return False
		
		c = unichr (key.code)
		if ascii.ispunct (key.code): # if key code is a punctation
			if self._full_width_punct[self._mode]:
				self.commit_string (self._convert_to_full_width (c))
				return True
			else:
				self.commit_string (c)
				return True
			
		if self._full_width_letter[self._mode]: # if key code is a letter or digit
			self.commit_string (self._convert_to_full_width (c))
			return True
		else:
			self.commit_string (c)
			return True
		
		# should not reach there
		return False
	
	def _table_mode_process_key_event (self, key):
		'''Xingma Mode Process Key Event'''
		cond_letter_translate = lambda (c): \
			self._convert_to_full_width (c) if self._full_width_letter [self._mode] else c
		cond_punct_translate = lambda (c): \
			self._convert_to_full_width (c) if self._full_width_punct [self._mode] else c
		
		# We have to process the pinyin mode change key event here,
		# because we ignore all Release event below.
		if self._match_hotkey (key, keysyms.Shift_R, modifier.SHIFT_MASK + modifier.RELEASE_MASK) and self._ime_py:
			res = self._editor.r_shift ()
			self._refresh_properties ()
			self._update_ui ()
			return res
		# process commit to preedit	
		if self._match_hotkey (key, keysyms.Shift_R, modifier.SHIFT_MASK + modifier.RELEASE_MASK) or self._match_hotkey (key, keysyms.Shift_L, modifier.SHIFT_MASK + modifier.RELEASE_MASK):
			res = self._editor.l_shift ()
			self._update_ui ()
			return res
		
		# Ignore key release event now :)
		if key.mask & modifier.RELEASE_MASK:
			return True

		if self._editor.is_empty ():
			# we have not input anything
			if key.code <= 127 and (not key.mask & modifier.ALT_MASK + modifier.CONTROL_MASK):
				if ascii.ispunct (key.code) and ( unichr(key.code) not in self._valid_input_chars ) :
					self.commit_string (cond_punct_translate (unichr (key.code)))
					return True
				if ascii.isdigit (key.code):
					self.commit_string (cond_letter_translate (unichr (key.code)))
					return True

		if key.code in (keysyms.Return, keysyms.KP_Enter):
			if self._editor.is_empty ():
				return False
			else:
				commit_string = self._editor.get_all_input_strings ()
				self._editor.clear ()
				self._update_ui ()
				self.commit_string (commit_string)
				self._refresh_properties ()
				return True
		
		elif key.code == keysyms.Escape:
			if self._editor.is_empty () and (not self._editor._py_mode) :
				return False
			else:
				self.reset ()
				self._update_ui ()
				return True
		
		elif key.code in (keysyms.Down, keysyms.KP_Down) :
			res = self._editor.arrow_down ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Up, keysyms.KP_Up):
			res = self._editor.arrow_up ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Left, keysyms.KP_Left) and key.mask & modifier.CONTROL_MASK:
			res = self._editor.control_arrow_left ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Right, keysyms.KP_Right) and key.mask & modifier.CONTROL_MASK:
			res = self._editor.control_arrow_right ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Left, keysyms.KP_Left):
			res = self._editor.arrow_left ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Right, keysyms.KP_Right):
			res = self._editor.arrow_right ()
			self._update_ui ()
			return res
		
		elif key.code == keysyms.BackSpace and key.mask & modifier.CONTROL_MASK:
			res = self._editor.control_backspace ()
			self._update_ui ()
			return res
		
		elif key.code == keysyms.BackSpace:
			res = self._editor.backspace ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Delete, keysyms.KP_Delete) and key.mask & modifier.CONTROL_MASK:
			res = self._editor.control_delete ()
			self._update_ui ()
			return res
		
		elif key.code in (keysyms.Delete, keysyms.KP_Delete):
			res = self._editor.delete ()
			self._update_ui ()
			return res

		elif key.code >= keysyms._1 and key.code <= keysyms._9 and self._editor._candidates[0] and key.mask & modifier.CONTROL_MASK:
			res = self._editor.number (key.code - keysyms._1)
			self._update_ui ()
			return res
		elif key.code >= keysyms.KP_1 and key.code <= keysyms.KP_9 and self._editor._candidates[0] and key.mask & modifier.CONTROL_MASK:
			res = self._editor.number (key.code - keysyms.KP_1)
			self._update_ui ()
			return res

		elif key.code >= keysyms._1 and key.code <= keysyms._9 and self._editor._candidates[0] and key.mask & modifier.ALT_MASK:
			res = self._editor.alt_number (key.code - keysyms._1)
			self._update_ui ()
			return res
		elif key.code >= keysyms.KP_1 and key.code <= keysyms.KP_9 and self._editor._candidates[0] and key.mask & modifier.ALT_MASK:
			res = self._editor.alt_number (key.code - keysyms.KP_1)
			self._update_ui ()
			return res

		elif key.code in (keysyms.KP_Space, keysyms.space):
			sp_res = self._editor.space ()
			self._update_ui ()
			#return (KeyProcessResult,whethercommit,commitstring)
			if sp_res[0]:
				self.commit_string (sp_res[1])
				self.db.check_phrase (sp_res[1])
				self._refresh_properties ()
			else:
				self.commit_string (cond_letter_translate (u" "))
			return True
		# now we ignore all else hotkeys
		elif key.mask & modifier.CONTROL_MASK+modifier.ALT_MASK:
			return False

		elif key.mask & modifier.ALT_MASK:
			return False

		elif unichr(key.code) in self._valid_input_chars or \
				( self._editor._py_mode and \
					unichr(key.code) in u'abcdefghijklmnopqrstuvwxyz' ):
			res = self._editor.add_input ( unichr(key.code) )
			if not res:
				if ascii.ispunct (key.code):
					key_char = cond_punct_translate (unichr (key.code))
				else:
					key_char = cond_letter_translate (unichr (key.code))
				sp_res = self._editor.space ()
				self._update_ui ()
				#return (KeyProcessResult,whethercommit,commitstring)
				if sp_res[0]:
					self.commit_string (sp_res[1] + key_char)
					self.db.check_phrase (sp_res[1])
					self._refresh_properties ()
				else:
					self.commit_string ( key_char )

			self._update_ui ()
			return True
		
		elif key.code in (keysyms.equal, keysyms.Page_Down, keysyms.KP_Page_Down) and self._editor._candidates[0]:
			res = self._editor.page_down()
			self._update_ui ()
			return res

		elif key.code in (keysyms.minus, keysyms.Page_Up, keysyms.KP_Page_Up) and self._editor._candidates[0]:
			res = self._editor.page_up ()
			self._update_ui ()
			return res
		
		elif key.code >= keysyms._1 and key.code <= keysyms._9 and self._editor._candidates[0]:
			res = self._editor.number (key.code - keysyms._1)
			if res:
				commit_string = self._editor.get_preedit_strings ()
				self._editor.clear ()
				self.commit_string (commit_string)
				# modify freq info
				self.db.check_phrase (commit_string)
				self._refresh_properties ()
			self._update_ui ()
			return True
		
		elif key.code >= keysyms.KP_1 and key.code <= keysyms.KP_9 and self._editor._candidates[0]:
			res = self._editor.number (key.code - keysyms.KP_1)
			if res:
				commit_string = self._editor.get_preedit_strings ()
				self._editor.clear ()
				self.commit_string (commit_string)
				self.db.check_phrase (commit_string)
				self._refresh_properties ()
			self._update_ui ()
			return res
		
		elif key.code <= 127:
			self._editor.commit_to_preedit ()
			commit_string = self._editor.get_preedit_strings ()
			self._editor.clear ()
			self._refresh_properties ()
			self._update_ui ()
			if ascii.ispunct (key.code):
				self.commit_string ( commit_string + cond_punct_translate (unichr (key.code)))
			else:
				self.commit_string ( commit_string + cond_letter_translate (unichr (key.code)))
			return True
		return False
	
	# below for initial test
	def focus_in (self):
		self.register_properties (self.properties)
		self._refresh_properties ()
		self._update_ui ()
	
	def focus_out (self):
		pass

	def lookup_table_page_up (self):
		if self._editor.page_up ():
			self._update_lookup_table ()
			return True
		return True

	def lookup_table_page_down (self):
		if self._editor.page_down ():
			self._update_lookup_table ()
			return True
		return False
	
	