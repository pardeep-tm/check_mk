// +------------------------------------------------------------------+
// |             ____ _               _        __  __ _  __           |
// |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
// |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
// |           | |___| | | |  __/ (__|   <    | |  | | . \            |
// |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
// |                                                                  |
// | Copyright Mathias Kettner 2015             mk@mathias-kettner.de |
// +------------------------------------------------------------------+
//
// This file is part of Check_MK.
// The official homepage is at http://mathias-kettner.de/check_mk.
//
// check_mk is free software;  you can redistribute it and/or modify it
// under the  terms of the  GNU General Public License  as published by
// the Free Software Foundation in version 2.  check_mk is  distributed
// in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
// out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
// PARTICULAR PURPOSE. See the  GNU General Public License for more de-
// ails.  You should have  received  a copy of the  GNU  General Public
// License along with GNU Make; see the file  COPYING.  If  not,  write
// to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
// Boston, MA 02110-1301 USA.


#ifndef wmiHelper_h
#define wmiHelper_h


#include <stdexcept>
#include <windows.h>
#include <wbemidl.h>
#include <vector>



std::string to_utf8(const wchar_t *string);


namespace wmi {


struct ComException : public std::runtime_error {
    ComException(const std::string &message, HRESULT result);
private:
    IErrorInfo *getErrorInfo();
    std::string toStringHex(HRESULT res);
};


struct ComTypeException : public std::runtime_error {
    ComTypeException(const std::string &message);
};


class Variant
{

    VARIANT _value;

public:

    Variant(const VARIANT &val);
    ~Variant();

    template <typename T> T get();

private:
};


template <> int Variant::get();
template <> ULONG Variant::get();
template <> ULONGLONG Variant::get();
template <> std::string Variant::get();
template <> std::wstring Variant::get();


class ObjectWrapper {

    friend class Helper;

    bool _owner;

protected:

    IWbemClassObject *_current;

public:

    ObjectWrapper(IWbemClassObject *object);

    ObjectWrapper(const ObjectWrapper &reference);
    ~ObjectWrapper();

    bool contains(const wchar_t *key) const;

    // retrieve the id of the data type at the specified key. Please see
    // https://msdn.microsoft.com/en-us/library/windows/desktop/ms221170%28v=vs.85%29.aspx
    // for the meaning of the returned id
    int typeId(const wchar_t *key) const;

    // retrieve the value at the specified column key in the current row.
    // if the value can't be converted to the specified data type, an exception is
    // thrown.
    template <typename T> T get(const wchar_t *key) const;

private:

    // not implemented
    ObjectWrapper &operator=(const ObjectWrapper &reference);


    VARIANT getVarByKey(const wchar_t *key) const;

};


template <typename T> T ObjectWrapper::get(const wchar_t *key) const
{
    Variant value(getVarByKey(key));
    try {
        return value.get<T>();
    } catch (const ComTypeException &e) {
        throw ComTypeException(std::string("failed to retrieve ") + to_utf8(key) + ": " + e.what());
    }
}


class Result : public ObjectWrapper
{
    IEnumWbemClassObject *_enumerator;

public:

    Result(IEnumWbemClassObject *enumerator);
    ~Result();

    std::vector<std::wstring> names() const;

    // proceed to the next element.
    // returns true on success, false if there are no more elements. An exception
    // is thrown if an error happens (i.e. timeout in the query).
    // unless true is returned, the current element is not changed, to once the end
    // of the result has been reached, the iterator stays there.
    bool next();

    // return true if this is a valid result. Please note that
    // once a result is valid it remains so, it doesn't become invalid
    // if an error during iteration happens or the last row has been reached.
    bool valid() const;

};


class Helper
{

    IWbemLocator *_locator;
    IWbemServices *_services;
    std::wstring _path;

public:

    Helper(LPCWSTR path = L"Root\\Cimv2");
    ~Helper();

    Result query(LPCWSTR query);

    ObjectWrapper call(ObjectWrapper &result, LPCWSTR method);

private:

    void initCOM();
    void deinitCOM();

    // get a locator that is used to look up WMI namespaces
    IWbemLocator *getWBEMLocator();

    // connect to a wmi namespace. returns a "proxy" to that namespace
    IWbemServices *connectServer(IWbemLocator *locator);

    // sets authentication information on the services proxy
    void setProxyBlanket(IWbemServices *services);

};

} // namespace wmi

#endif // wmiHelper_h
